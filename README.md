# Taller — Monitor de procesos (`/proc`)

Herramienta en Python (sin dependencias externas) que lee directamente el sistema de archivos virtual `/proc` del kernel Linux para mostrar:
- El uso de CPU en tiempo real **por núcleo** (`CPU0`, `CPU1`, ...) y total.
- El listado de procesos activos con su **PID**, **%CPU**, **núcleo asignado por el planificador**, **estado** (`R`, `S`, `D`, `I`, `Z`, `T`) y **nombre**.

## ¿De dónde sale la información?

| Archivo en `/proc` | Qué se lee |
|---|---|
| `/proc/stat` | Tiempos acumulados por cada núcleo (`user`, `nice`, `system`, `idle`, `iowait`, etc.). Calculando la diferencia entre dos instantes se obtiene el porcentaje real de uso de cada núcleo. |
| `/proc/<pid>/status` | Los campos `Name:` (nombre del proceso) y `State:` (estado actual: `R` en ejecución, `S` en espera, etc.). |
| `/proc/<pid>/stat` | Los campos `utime`, `stime` (tiempo de CPU consumido por el proceso) y el campo `processor` (último núcleo en el que el planificador ejecutó el proceso). |

## Ejecución

En una terminal de Linux (o WSL / contenedor Linux):

```bash
python3 monitor.py
```

Opciones útiles:
- `python3 monitor.py -r` — Muestra únicamente procesos en estado `R` (*En ejecución*).
- `python3 monitor.py -i 0.5` — Actualiza cada 0.5 segundos.
- `python3 monitor.py -n 20` — Muestra los 20 procesos principales.

## Prueba de estrés de CPU (Paso 2 del taller)

En otra terminal, ejecuta alguno de los siguientes comandos mientras `monitor.py` está corriendo:

### Opción A: Usando `stress-ng`
```bash
sudo apt install -y stress-ng
stress-ng --cpu 4 --timeout 60s
```

### Opción B: Alternativa con `yes`
```bash
yes > /dev/null &
yes > /dev/null &
yes > /dev/null &
yes > /dev/null &
```
Para detener los procesos `yes` al terminar:
```bash
killall yes
```

Durante la prueba observarás cómo los núcleos (`CPU0`..`CPU3`) suben cerca del 100% y cómo el planificador reparte los procesos de `stress-ng` o `yes` (en estado `R`) entre los distintos núcleos. En ese momento toma la captura de pantalla para el entregable.
