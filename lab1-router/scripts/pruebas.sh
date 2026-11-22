#!/bin/bash

set -e

BASE="$(cd "$(dirname "$0")/.." && pwd)"

echo "===================================="
echo " PRUEBAS DEL ROUTER IPv4 EN P4"
echo "===================================="

echo ""
echo "[1] Compilando router P4..."

mkdir -p "$BASE/build"

p4c-bm2-ss --arch v1model \
    -o "$BASE/build/router.json" \
    "$BASE/router.p4"

echo "Compilacion exitosa."

echo ""
echo "[2] Verificando topologia de Mininet..."

python3 -m py_compile "$BASE/topology.py"

echo "Sintaxis correcta."

echo ""
echo "[3] Verificando tablas de enrutamiento..."

for router in s1 s2 s3; do
    archivo="$BASE/tables/$router.txt"

    if [ ! -f "$archivo" ]; then
        echo "ERROR: No existe $archivo"
        exit 1
    fi

    cantidad=$(grep -c '^table_add ipv4_lpm' "$archivo")

    echo "$router: $cantidad rutas configuradas"

    if [ "$cantidad" -ne 4 ]; then
        echo "ERROR: Se esperaban 4 rutas en $router"
        exit 1
    fi
done

echo ""
echo "===================================="
echo " VERIFICACIONES INICIALES EXITOSAS"
echo "===================================="

echo ""
echo "Para ejecutar las pruebas de conectividad:"
echo "sudo python3 $BASE/topology.py"
echo ""
echo "Dentro de Mininet:"
echo "  pingall"
echo "  h1 ping -c 3 -t 64 10.0.4.10"
echo "  h1 ping -c 3 -W 1 -t 2 10.0.4.10"
echo "  h1 ping -c 3 -W 1 10.0.5.10"
