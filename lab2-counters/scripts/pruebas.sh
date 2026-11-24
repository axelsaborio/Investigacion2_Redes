#!/bin/bash

set -e

BASE="$(cd "$(dirname "$0")/.." && pwd)"

echo "===================================="
echo " PRUEBAS DEL SISTEMA DE CONTADORES"
echo "===================================="

echo ""
echo "[1] Compilando counters.p4..."

mkdir -p "$BASE/build"

p4c-bm2-ss --arch v1model \
    -o "$BASE/build/counters.json" \
    "$BASE/counters.p4"

echo "Compilacion exitosa."

echo ""
echo "[2] Verificando contadores y registers en el programa compilado..."

for objeto in proto_counter flow_counter flow_bytes flow_pkt_min \
              flow_pkt_max flow_elephant size_hist elephant_threshold; do
    if ! grep -q "\"MyIngress.$objeto\"" "$BASE/build/counters.json"; then
        echo "ERROR: falta $objeto en counters.json"
        exit 1
    fi
    echo "  $objeto: OK"
done

echo ""
echo "[3] Verificando sintaxis de los programas Python..."

python3 -m py_compile \
    "$BASE/topology.py" \
    "$BASE/controller.py" \
    "$BASE/scripts/generar_trafico.py" \
    "$BASE/scripts/prueba_automatica.py"

echo "Sintaxis correcta."

echo ""
echo "[4] Verificando las entradas de las tablas..."

archivo="$BASE/tables/s1.txt"

if [ ! -f "$archivo" ]; then
    echo "ERROR: No existe $archivo"
    exit 1
fi

reenvio=$(grep -c '^table_add ipv4_forward' "$archivo")
flujos=$(grep -c '^table_add flow_stats' "$archivo")

echo "  Entradas de reenvio: $reenvio"
echo "  Flujos monitoreados: $flujos"

if [ "$reenvio" -ne 4 ] || [ "$flujos" -ne 12 ]; then
    echo "ERROR: se esperaban 4 entradas de reenvio y 12 flujos"
    exit 1
fi

echo ""
echo "===================================="
echo " VERIFICACIONES INICIALES EXITOSAS"
echo "===================================="

if [ "$1" == "--completo" ]; then
    echo ""
    echo "[5] Ejecutando las pruebas en Mininet..."
    sudo mn -c > /dev/null 2>&1
    sudo python3 "$BASE/scripts/prueba_automatica.py"
else
    echo ""
    echo "Para ejecutar las 6 pruebas automaticas en Mininet:"
    echo "  ./lab2-counters/scripts/pruebas.sh --completo"
    echo ""
    echo "Para probar manualmente:"
    echo "  sudo python3 lab2-counters/topology.py"
    echo "  (otra terminal) python3 lab2-counters/controller.py"
fi
