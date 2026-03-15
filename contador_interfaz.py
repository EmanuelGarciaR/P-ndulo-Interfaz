import serial
import time
import csv
from bisect import bisect_left
from pathlib import Path
import matplotlib.pyplot as plt
import msvcrt

# --- CONFIGURACIÓN ---
PUERTO = 'COM3'
BAUDIOS = 115200
ARCHIVO_TRACKER = 'tracker.csv'
USAR_DEBUG_SI_NO_ARDUINO = True

modo_debug_teclado = False
try:
    arduino = serial.Serial(PUERTO, BAUDIOS, timeout=1)
    time.sleep(2)  
    print(f"Conectado exitosamente al {PUERTO}")
except Exception as e:
    if USAR_DEBUG_SI_NO_ARDUINO:
        modo_debug_teclado = True
        arduino = None
        print(f"No se pudo conectar al Arduino ({e}). Entrando en modo DEBUG.")
    else:
        print(f"Error al conectar: {e}")
        exit()

# Listas para almacenar datos
tiempos_eventos = []      # Tiempo que envía el Arduino (micros)
tiempos_pc_reales = []    # Tiempo real del sistema (PC)

def resolver_ruta_tracker(nombre_preferido):
    base_dir = Path(__file__).resolve().parent
    candidatos = [Path(nombre_preferido), base_dir / nombre_preferido, Path('tracker.csv'), base_dir / 'tracker.csv']
    for ruta in candidatos:
        if ruta.exists() and ruta.is_file():
            return str(ruta.resolve()), []
    return None, [str(c) for c in candidatos]

def cargar_tracker(ruta_csv):
    tiempos, posiciones = [], []
    with open(ruta_csv, newline='', encoding='utf-8-sig') as archivo:
        lector = csv.DictReader(archivo)
        for fila in lector:
            try:
                tiempos.append(float(fila['t']))
                posiciones.append(float(fila['x']))
            except: continue
    return tiempos, posiciones

def centrar_en_equilibrio(serie):
    equilibrio = sum(serie) / len(serie)
    return [valor - equilibrio for valor in serie], equilibrio

def calcular_cruces_equilibrio(tiempos, posiciones_centradas):
    cruces = []
    for i in range(1, len(posiciones_centradas)):
        y1, y2 = posiciones_centradas[i-1], posiciones_centradas[i]
        if y1 * y2 < 0:
            t1, t2 = tiempos[i-1], tiempos[i]
            t_cruce = t1 + (-y1 / (y2 - y1)) * (t2 - t1)
            cruces.append(t_cruce)
    return sorted(cruces)

def calcular_errores_absolutos(eventos, cruces_tracker):
    if not eventos or not cruces_tracker: return [], []
    eventos_ref, errores_abs = [], []
    for t_evento in eventos:
        indice = bisect_left(cruces_tracker, t_evento)
        candidatos = [cruces_tracker[i] for i in [indice-1, indice] if 0 <= i < len(cruces_tracker)]
        if candidatos:
            t_cercano = min(candidatos, key=lambda t: abs(t - t_evento))
            eventos_ref.append(t_evento)
            errores_abs.append(abs(t_evento - t_cercano))
    return eventos_ref, errores_abs

def extraer_tiempo_evento(linea):
    try:
        partes = [float(p) for p in linea.replace(';', ',').split(',') if p.strip()]
        return partes[0] if partes else None
    except: return None

# --- BUCLE DE CAPTURA ---
print("\nRegistrando... Presiona 'Ctrl + C' para finalizar y graficar.\n")
try:
    t_debug = 0.0
    while True:
        if modo_debug_teclado:
            if msvcrt.kbhit():
                tecla = msvcrt.getwch()
                if tecla == ' ':
                    t_debug += 0.5 
                    tiempos_eventos.append(t_debug)
                    tiempos_pc_reales.append(time.time()) # <--- AQUÍ: Tiempo PC
                    print(f"DEBUG -> t: {t_debug}s")
                elif tecla.lower() == 'q': raise KeyboardInterrupt
            time.sleep(0.01)
        elif arduino.in_waiting > 0:
            linea = arduino.readline().decode('utf-8', errors='ignore').strip()
            t_evento = extraer_tiempo_evento(linea)
            if t_evento is not None:
                tiempos_eventos.append(t_evento)
                tiempos_pc_reales.append(time.time()) # <--- AQUÍ: Tiempo PC
                print(f"Arduino -> t: {t_evento:.3f}s")
except KeyboardInterrupt:
    print("\nProcesando resultados...")

# --- PROCESAMIENTO Y GRÁFICAS ---
try:
    ruta_tracker, _ = resolver_ruta_tracker(ARCHIVO_TRACKER)
    tiempos_t, x_t = cargar_tracker(ruta_tracker)
    x_t_centrada, eq_t = centrar_en_equilibrio(x_t)
    tiempos_t_alineados = [t - tiempos_t[0] for t in tiempos_t]
    cruces_t = calcular_cruces_equilibrio(tiempos_t_alineados, x_t_centrada)

    # 1. Sincronización para Error vs Tracker
    tiempos_arduino_vs_tracker = []
    if tiempos_eventos and cruces_t:
        offset = cruces_t[0] - tiempos_eventos[0]
        tiempos_arduino_vs_tracker = [t + offset for t in tiempos_eventos]

    ev_ref_t, err_t = calcular_errores_absolutos(tiempos_arduino_vs_tracker, cruces_t)

    # 2. Sincronización para Error vs Tiempo Real (PC)
    ev_ref_pc, err_pc = [], []
    if len(tiempos_eventos) > 1:
        t0_arduino = tiempos_eventos[0]
        t0_pc = tiempos_pc_reales[0]
        for i in range(len(tiempos_eventos)):
            d_arduino = tiempos_eventos[i] - t0_arduino
            d_pc = tiempos_pc_reales[i] - t0_pc
            ev_ref_pc.append(d_arduino)
            err_pc.append(abs(d_arduino - d_pc))

    # --- RENDERIZADO ---
    plt.style.use('dark_background')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 12), sharex=True)

    # Gráfica 1: Movimiento y Cruces
    ax1.plot(tiempos_t_alineados, x_t_centrada, color='#ff3b30', linewidth=0.8, label='Tracker')
    ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
    if tiempos_arduino_vs_tracker:
        ax1.scatter(tiempos_arduino_vs_tracker, [0]*len(tiempos_arduino_vs_tracker), color='#34c759', s=50, zorder=5, label='Arduino')
    ax1.set_title('Superposición Física (Referencia: Tracker)')
    ax1.legend()

    # Gráfica 2: Error del Sensor (vs Tracker)
    if err_t:
        ax2.fill_between(ev_ref_t, err_t, color='cyan', alpha=0.2)
        ax2.plot(ev_ref_t, err_t, color='cyan', label='Error Sensor (s)')
    ax2.set_title('Precisión del Sensor (Arduino detectando el centro)')
    ax2.set_ylabel('|Δt| (s)')

    # Gráfica 3: Precisión del Péndulo (vs Reloj PC)
    if err_pc:
        ax3.fill_between(ev_ref_pc, err_pc, color='magenta', alpha=0.2)
        ax3.plot(ev_ref_pc, err_pc, color='magenta', label='Deriva Reloj (s)')
    ax3.set_title('Precisión del Reloj de Péndulo (Comparado con Tiempo Real PC)')
    ax3.set_ylabel('|Δt| (s)')
    ax3.set_xlabel('Tiempo (s)')

    plt.tight_layout()
    plt.show()

except Exception as e:
    print(f"Error al generar gráficas: {e}")