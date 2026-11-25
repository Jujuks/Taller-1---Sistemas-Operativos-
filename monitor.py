#!/usr/bin/env python3
"""
Monitor de procesos y reparto de CPU en tiempo real leyendo directamente /proc.

Fuentes de información del kernel Linux utilizadas:
  - /proc/stat          : Tiempos acumulados por cada núcleo lógico (cpu0, cpu1, ...).
  - /proc/<pid>/status  : Nombre del proceso (Name) y estado legible (State).
  - /proc/<pid>/stat    : Tiempos de CPU del proceso (utime, stime) y último núcleo (processor).
"""

import argparse
import os
import shutil
import sys
import time

# Códigos ANSI para limpiar pantalla y dar color sin dependencias externas
CLEAR_HOME = "\033[H\033[J"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

STATE_DESCRIPTIONS = {
    "R": "En ejecución",
    "S": "En espera (sleep)",
    "D": "Espera ininterrumpible",
    "I": "Inactivo (idle)",
    "T": "Detenido",
    "t": "Detenido (debug)",
    "Z": "Zombie",
    "X": "Muerto",
}


def read_cpu_times():
    """Lee /proc/stat y retorna {cpu_name: (activo, total)} para cpu y cpu0..cpuN."""
    cpus = {}
    with open("/proc/stat", "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("cpu"):
                continue
            parts = line.split()
            name = parts[0]
            values = [int(x) for x in parts[1:]]
            # user, nice, system, idle, iowait, irq, softirq, steal, ...
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            active = total - idle
            cpus[name] = (active, total)
    return cpus


def read_process_info(pid):
    """
    Lee /proc/<pid>/status y /proc/<pid>/stat para un PID dado.
    Retorna un diccionario con los datos o None si el proceso terminó.
    """
    status_path = f"/proc/{pid}/status"
    stat_path = f"/proc/{pid}/stat"

    name = "?"
    state_code = "?"
    state_raw = "?"

    try:
        with open(status_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("State:"):
                    state_raw = line.split(":", 1)[1].strip()
                    state_code = state_raw.split()[0] if state_raw else "?"
                if name != "?" and state_code != "?":
                    break

        with open(stat_path, "r", encoding="utf-8", errors="replace") as f:
            stat_line = f.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None

    # El campo comm en /proc/<pid>/stat está entre paréntesis y puede contener espacios.
    rparen = stat_line.rfind(")")
    if rparen == -1:
        return None

    fields_after_comm = stat_line[rparen + 2 :].split()
    # En /proc/<pid>/stat:
    #   índice 0 -> campo 3 (state)
    #   índice 11 -> campo 14 (utime)
    #   índice 12 -> campo 15 (stime)
    #   índice 36 -> campo 39 (processor: último núcleo en el que corrió)
    try:
        utime = int(fields_after_comm[11])
        stime = int(fields_after_comm[12])
        processor = int(fields_after_comm[36])
    except (IndexError, ValueError):
        return None

    return {
        "pid": pid,
        "name": name,
        "state_code": state_code,
        "state_desc": STATE_DESCRIPTIONS.get(state_code, state_raw),
        "proc_ticks": utime + stime,
        "cpu": processor,
    }


def list_pids():
    """Retorna la lista de PIDs numéricos presentes actualmente en /proc."""
    pids = []
    try:
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                pids.append(int(entry))
    except OSError:
        pass
    return pids


def render_bar(percent, width=24):
    """Genera una barra ASCII coloreada según el porcentaje de uso."""
    clamped = max(0.0, min(100.0, percent))
    filled = int(round((clamped / 100.0) * width))
    bar = "|" * filled + "." * (width - filled)
    if clamped >= 80.0:
        color = RED
    elif clamped >= 40.0:
        color = YELLOW
    else:
        color = GREEN
    return f"{color}[{bar}] {clamped:5.1f}%{RESET}"


def collect_snapshot(prev_cpus, prev_proc_ticks, prev_total_cpu_ticks):
    """Toma una muestra de /proc y calcula %CPU por núcleo y por proceso."""
    curr_cpus = read_cpu_times()

    cpu_usages = {}
    for name, (act, tot) in curr_cpus.items():
        p_act, p_tot = prev_cpus.get(name, (act, tot))
        d_tot = tot - p_tot
        d_act = act - p_act
        cpu_usages[name] = (d_act / d_tot * 100.0) if d_tot > 0 else 0.0

    _, curr_total_all = curr_cpus.get("cpu", (0, 0))
    d_total_all = curr_total_all - prev_total_cpu_ticks
    num_cores = max(1, sum(1 for k in curr_cpus if k != "cpu"))

    processes = []
    curr_proc_ticks = {}
    state_counts = {"R": 0, "S": 0, "other": 0}

    for pid in list_pids():
        info = read_process_info(pid)
        if info is None:
            continue

        curr_proc_ticks[pid] = info["proc_ticks"]
        prev_ticks = prev_proc_ticks.get(pid)
        if prev_ticks is not None and d_total_all > 0:
            # Multiplicamos por num_cores para que 100% equivalga a 1 núcleo saturado (estilo top)
            cpu_pct = ((info["proc_ticks"] - prev_ticks) / d_total_all) * 100.0 * num_cores
        else:
            cpu_pct = 0.0

        info["cpu_pct"] = max(0.0, cpu_pct)
        processes.append(info)

        sc = info["state_code"]
        if sc == "R":
            state_counts["R"] += 1
        elif sc in ("S", "I"):
            state_counts["S"] += 1
        else:
            state_counts["other"] += 1

    # Ordenar primero por %CPU descendente y luego por estado 'R' arriba
    processes.sort(
        key=lambda p: (round(p["cpu_pct"], 2), p["state_code"] == "R", -p["pid"]),
        reverse=True,
    )

    return curr_cpus, curr_proc_ticks, curr_total_all, cpu_usages, processes, state_counts


def print_frame(cpu_usages, processes, state_counts, max_rows, only_running):
    """Imprime la vista del monitor en la terminal."""
    term_cols, term_rows = shutil.get_terminal_size((80, 24))
    lines = []

    lines.append(f"{BOLD}{CYAN}=== Monitor de Procesos y Planificador de CPU (/proc) ==={RESET}")
    lines.append(
        f"Total procesos: {BOLD}{len(processes)}{RESET} | "
        f"{GREEN}En ejecución (R): {state_counts['R']}{RESET} | "
        f"En espera (S/I): {state_counts['S']} | "
        f"Otros: {state_counts['other']}"
    )
    lines.append("")

    # Mostrar uso global y por núcleo
    core_names = sorted(
        (k for k in cpu_usages if k != "cpu"),
        key=lambda k: int(k[3:]) if k[3:].isdigit() else 0,
    )
    if "cpu" in cpu_usages:
        lines.append(f"  {BOLD}TOTAL{RESET} : {render_bar(cpu_usages['cpu'])}")
    for core in core_names:
        lines.append(f"  {core.upper():<5} : {render_bar(cpu_usages[core])}")

    lines.append("")
    header = f"{BOLD}{'PID':>7}  {'CPU%':>6}  {'NÚCLEO':>6}  {'EST':<3}  {'ESTADO':<22}  {'NOMBRE'}{RESET}"
    lines.append(header)
    lines.append("-" * min(term_cols, 78))

    filtered = [p for p in processes if not only_running or p["state_code"] == "R"]
    # Reservar espacio para la cabecera si max_rows es automático
    limit = max_rows if max_rows > 0 else max(5, term_rows - len(lines) - 2)

    for proc in filtered[:limit]:
        sc = proc["state_code"]
        color = GREEN if sc == "R" else (YELLOW if sc == "D" else RESET)
        row = (
            f"{proc['pid']:>7}  "
            f"{proc['cpu_pct']:>5.1f}%  "
            f"  CPU{proc['cpu']:<2}  "
            f"{color}{sc:<3}  {proc['state_desc']:<22}{RESET}  "
            f"{proc['name']}"
        )
        lines.append(row[:term_cols])

    lines.append(f"\n{DIM}Actualizando... Presiona Ctrl+C para salir.{RESET}")
    sys.stdout.write(CLEAR_HOME + "\n".join(lines) + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Monitor de procesos y núcleos de CPU leyendo /proc."
    )
    parser.add_argument(
        "-i", "--interval", type=float, default=1.0,
        help="Intervalo de actualización en segundos (por defecto: 1.0)"
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=0,
        help="Máximo de procesos a mostrar (0 = automático según altura de terminal)"
    )
    parser.add_argument(
        "-r", "--running-only", action="store_true",
        help="Mostrar únicamente procesos en estado R (En ejecución)"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Tomar una sola medición de intervalo y salir"
    )
    args = parser.parse_args()

    if not os.path.isdir("/proc"):
        sys.exit("Error: No se encontró el sistema de archivos /proc (requiere Linux).")

    # Muestra inicial para tener línea base de deltas de CPU
    prev_cpus = read_cpu_times()
    _, prev_total_all = prev_cpus.get("cpu", (0, 0))
    prev_proc_ticks = {}
    for pid in list_pids():
        info = read_process_info(pid)
        if info is not None:
            prev_proc_ticks[pid] = info["proc_ticks"]

    try:
        while True:
            time.sleep(args.interval)
            (
                prev_cpus,
                prev_proc_ticks,
                prev_total_all,
                cpu_usages,
                processes,
                state_counts,
            ) = collect_snapshot(prev_cpus, prev_proc_ticks, prev_total_all)

            print_frame(
                cpu_usages,
                processes,
                state_counts,
                args.limit,
                args.running_only,
            )
            if args.once:
                break
    except KeyboardInterrupt:
        print(f"\n{RESET}Monitor finalizado.")


if __name__ == "__main__":
    main()
