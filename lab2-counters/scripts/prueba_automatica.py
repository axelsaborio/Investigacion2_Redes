#!/usr/bin/env python3

import re
import signal
import subprocess
import sys
import time

from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from mininet.log import setLogLevel

import controller
import topology


GENERADOR = BASE / "scripts" / "generar_trafico.py"
CONTROLADOR = BASE / "controller.py"
RESULTADOS = BASE / "resultados_pruebas.txt"

UMBRAL = 100000

lineas_reporte = []
resultados = []


def reportar(texto=""):
    print(texto)
    lineas_reporte.append(texto)


def verificar(prueba, descripcion, esperado, obtenido, condicion=None):
    correcto = (esperado == obtenido) if condicion is None else condicion
    estado = "PASA " if correcto else "FALLA"
    reportar(f"  [{estado}] {descripcion}: esperado {esperado}, "
             f"obtenido {obtenido}")
    resultados.append((prueba, correcto))
    return correcto


def reiniciar_contadores(switch):
    switch.ejecutar([
        f"counter_reset {controller.CONTADOR_PROTOCOLO}",
        f"counter_reset {controller.CONTADOR_FLUJO}",
        f"register_reset {controller.REG_BYTES}",
        f"register_reset {controller.REG_MINIMO}",
        f"register_reset {controller.REG_MAXIMO}",
        f"register_reset {controller.REG_HISTOGRAMA}",
        f"register_reset {controller.REG_ELEFANTE}",
        f"register_write {controller.REG_UMBRAL} 0 {UMBRAL}",
    ])


def generar(host, argumentos):
    salida = host.cmd(f"python3 {GENERADOR} {argumentos}")
    for linea in salida.strip().splitlines():
        reportar(f"    {linea}")
    time.sleep(1)


def flujo(datos, origen, destino):
    for f in datos["flujos"]:
        if f["origen"] == origen and f["destino"] == destino:
            return f
    raise KeyError(f"Flujo {origen} -> {destino} no encontrado")


def prueba_1(net):
    reportar("\nPRUEBA 1. Conectividad entre los cuatro hosts")
    perdida = net.pingAll(timeout=1)
    verificar(1, "Porcentaje de perdida en pingall", 0.0, perdida)


def prueba_2(net, switch, flujos):
    reportar("\nPRUEBA 2. Contadores por protocolo")
    reiniciar_contadores(switch)
    generar(net.get("h1"), "--destino 10.0.0.2 --tipo mixto "
                           "--cantidad 10 --tamano 200")

    datos = controller.leer_estadisticas(switch, flujos)
    p = datos["protocolos"]

    verificar(2, "Paquetes TCP (enviados + respuestas RST)", ">= 10",
              p["TCP"]["paquetes"], p["TCP"]["paquetes"] >= 10)
    verificar(2, "Paquetes UDP", 10, p["UDP"]["paquetes"])
    verificar(2, "Paquetes ICMP (eco + respuestas)", ">= 10",
              p["ICMP"]["paquetes"], p["ICMP"]["paquetes"] >= 10)
    verificar(2, "Paquetes OTROS (protocolo IP 253)", 10,
              p["OTROS"]["paquetes"])


def prueba_3(net, switch, flujos):
    reportar("\nPRUEBA 3. Contadores por flujo (IP origen + IP destino)")
    datos = controller.leer_estadisticas(switch, flujos)
    f12 = flujo(datos, "10.0.0.1", "10.0.0.2")
    f21 = flujo(datos, "10.0.0.2", "10.0.0.1")
    f13 = flujo(datos, "10.0.0.1", "10.0.0.3")

    verificar(3, "Paquetes del flujo 10.0.0.1 -> 10.0.0.2", 40,
              f12["paquetes"])
    verificar(3, "Bytes del flujo 10.0.0.1 -> 10.0.0.2", 8000, f12["bytes"])
    verificar(3, "Flujo inverso 10.0.0.2 -> 10.0.0.1 (solo respuestas)",
              "> 0", f21["paquetes"], f21["paquetes"] > 0)
    verificar(3, "Flujo sin trafico 10.0.0.1 -> 10.0.0.3", 0,
              f13["paquetes"])


def prueba_4(net, switch, flujos):
    reportar("\nPRUEBA 4. Registro de bytes con volumen conocido")
    reiniciar_contadores(switch)
    generar(net.get("h3"), "--destino 10.0.0.4 --tipo udp "
                           "--cantidad 100 --tamano 1000")

    datos = controller.leer_estadisticas(switch, flujos)
    f34 = flujo(datos, "10.0.0.3", "10.0.0.4")

    verificar(4, "Bytes en el contador directo del flujo", 100000,
              f34["bytes"])
    verificar(4, "Bytes en el register flow_bytes", 100000,
              f34["bytes_register"])
    verificar(4, "Bytes UDP en el contador por protocolo", 100000,
              datos["protocolos"]["UDP"]["bytes"])
    verificar(4, "Tamano minimo registrado", 1000, f34["minimo"])
    verificar(4, "Tamano maximo registrado", 1000, f34["maximo"])
    respuestas_icmp = datos["protocolos"]["ICMP"]["paquetes"]
    reportar(f"    Respuestas ICMP de h4 (puerto inalcanzable): "
             f"{respuestas_icmp}")
    verificar(4, "Paquetes en la categoria 512-1023 B del histograma "
                 "(100 UDP + respuestas ICMP)",
              100 + respuestas_icmp, datos["histograma"][2])


def prueba_5():
    reportar("\nPRUEBA 5. Actualizacion periodica del controlador")
    proceso = subprocess.Popen(
        [sys.executable, str(CONTROLADOR), "--intervalo", "5",
         "--sin-limpiar", "--umbral", str(UMBRAL)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    time.sleep(16)
    proceso.send_signal(signal.SIGINT)
    salida, _ = proceso.communicate(timeout=10)

    marcas = re.findall(r"(\d{2}:\d{2}:\d{2})  \|  lectura #(\d+)", salida)
    tiempos = [datetime.strptime(m[0], "%H:%M:%S") for m in marcas]
    diferencias = [(b - a).seconds for a, b in zip(tiempos, tiempos[1:])]

    for hora, numero in marcas:
        reportar(f"    lectura #{numero} a las {hora}")

    verificar(5, "Lecturas en 16 segundos", ">= 3", len(marcas),
              len(marcas) >= 3)
    verificar(5, "Segundos entre lecturas", "<= 5", diferencias,
              bool(diferencias) and max(diferencias) <= 5)


def prueba_6(net, switch, flujos):
    reportar("\nPRUEBA 6. Deteccion de flujos elefante")
    reiniciar_contadores(switch)
    generar(net.get("h1"), "--destino 10.0.0.3 --tipo elefante "
                           "--bytes 150000")
    generar(net.get("h2"), "--destino 10.0.0.4 --tipo udp "
                           "--cantidad 50 --tamano 1000")

    datos = controller.leer_estadisticas(switch, flujos)
    f13 = flujo(datos, "10.0.0.1", "10.0.0.3")
    f24 = flujo(datos, "10.0.0.2", "10.0.0.4")

    verificar(6, "Bytes del flujo 10.0.0.1 -> 10.0.0.3", 150000,
              f13["bytes"])
    verificar(6, "Marca del switch para 10.0.0.1 -> 10.0.0.3 (supera)",
              True, f13["marca_switch"])
    verificar(6, "Marca del switch para 10.0.0.2 -> 10.0.0.4 (50000 B)",
              False, f24["marca_switch"])

    salida = subprocess.run(
        [sys.executable, str(CONTROLADOR), "--una-vez", "--sin-limpiar",
         "--umbral", str(UMBRAL)],
        capture_output=True, text=True, timeout=30
    ).stdout

    alerta = salida[salida.find("ALERTA"):].strip().splitlines()
    for linea in alerta:
        reportar(f"    {linea}")

    verificar(6, "El controlador muestra la alerta", True,
              "ALERTA: Flujo elefante detectado" in salida)
    verificar(6, "Solo un flujo elefante reportado", 1,
              salida.count("ALERTA: Flujo elefante detectado"))


def main():
    setLogLevel("warning")

    reportar("=" * 70)
    reportar(" LABORATORIO 2 - PRUEBAS AUTOMATICAS")
    reportar(f" Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}")
    reportar("=" * 70)

    net = topology.crear_red()
    switch = controller.SwitchThrift(topology.THRIFT_PORT)

    try:
        flujos = controller.leer_flujos(switch)
        reportar(f"Flujos instalados en flow_stats: {len(flujos)}")

        prueba_1(net)
        prueba_2(net, switch, flujos)
        prueba_3(net, switch, flujos)
        prueba_4(net, switch, flujos)
        prueba_5()
        prueba_6(net, switch, flujos)
    finally:
        net.stop()

    reportar("\n" + "=" * 70)
    reportar(" RESUMEN")
    reportar("=" * 70)

    for numero in range(1, 7):
        estados = [ok for prueba, ok in resultados if prueba == numero]
        estado = "PASA" if estados and all(estados) else "FALLA"
        reportar(f" Prueba {numero}: {estado} "
                 f"({sum(estados)}/{len(estados)} comprobaciones)")

    total = sum(ok for _, ok in resultados)
    reportar(f"\n Total: {total}/{len(resultados)} comprobaciones correctas")

    RESULTADOS.write_text("\n".join(lineas_reporte) + "\n")
    print(f"\nResultados guardados en {RESULTADOS}")

    sys.exit(0 if total == len(resultados) else 1)


if __name__ == "__main__":
    main()
