# Simula todo el taller en un contenedor Linux real usando Docker Desktop.
# Inicia 4 procesos de carga (yes > /dev/null &) y ejecuta monitor.py en vivo.

Write-Host "Iniciando simulación de Linux con 4 procesos de estrés (yes)..." -ForegroundColor Cyan
Write-Host "Presiona Ctrl+C cuando hayas tomado tu captura de pantalla." -ForegroundColor Yellow

docker run --rm -it -v "${PWD}:/app" -w /app python:3.12-slim sh -c "yes > /dev/null & yes > /dev/null & yes > /dev/null & yes > /dev/null & python3 monitor.py -i 1.0"
