#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import time

from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent
ARCHIVO_ALERTAS = BASE / "elefantes.log"

PROTOCOLOS = ["TCP", "UDP", "ICMP", "OTROS"]
CATEGORIAS_TAMANO = ["0 - 127 B", "128 - 511 B", "512 - 1023 B", ">= 1024 B"]

CONTADOR_PROTOCOLO = "MyIngress.proto_counter"
CONTADOR_FLUJO = "MyIngress.flow_counter"
TABLA_FLUJOS = "MyIngress.flow_stats"
REG_BYTES = "MyIngress.flow_bytes"
REG_MINIMO = "MyIngress.flow_pkt_min"
REG_MAXIMO = "MyIngress.flow_pkt_max"
REG_ELEFANTE = "MyIngress.flow_elephant"
REG_HISTOGRAMA = "MyIngress.size_hist"
REG_UMBRAL = "MyIngress.elephant_threshold"

RE_CONTADOR_NUEVO = re.compile(
    r"(\S+)\[(\d+)\]=\s*\((\d+) bytes, (\d+) packets\)"
)
RE_CONTADOR_ANTIGUO = re.compile(
    r"(\S+)\[(\d+)\]=\s*BmCounterValue\(packets=(\d+), bytes=(\d+)\)"
)
RE_REGISTER = re.compile(r"(\S+)=\s*([\d,\s]+)$")
RE_ENTRADA = re.compile(r"Dumping entry (0x[0-9a-fA-F]+)")
RE_CAMPO_IP = re.compile(r"\*\s*(\S+)\s*:\s*EXACT\s+([0-9a-fA-F]+)")
RE_ACCION = re.compile(r"Action entry:\s*\S+\s*-\s*([0-9a-fA-F,\s]*)")


class SwitchThrift:
    def __init__(self, puerto):
        self.puerto = puerto

    def ejecutar(self, comandos):
        entrada = "\n".join(comandos) + "\n"

        try:
            resultado = subprocess.run(
                ["simple_switch_CLI", "--thrift-port", str(self.puerto)],
                input=entrada,
                text=True,
                capture_output=True,
                timeout=20
            )
        except FileNotFoundError:
            sys.exit("ERROR: no se encontro simple_switch_CLI en el PATH.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("El switch no respondio a tiempo.")

        salida = resultado.stdout + resultado.stderr

        if resultado.returncode != 0 or "Could not connect" in salida:
            raise RuntimeError(
                f"No fue posible comunicarse con el switch en el puerto "
                f"{self.puerto}. ¿Esta ejecutandose topology.py?"
            )

        return salida


def hex_a_ip(valor_hex):
    numero = int(valor_hex, 16)
    return ".".join(str((numero >> desplazamiento) & 0xFF)
                    for desplazamiento in (24, 16, 8, 0))


def formato_bytes(cantidad):
    if cantidad >= 1_000_000:
        return f"{cantidad / 1_000_000:.2f} MB"
    if cantidad >= 1_000:
        return f"{cantidad / 1_000:.1f} kB"
    return f"{cantidad:.0f} B"


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def leer_flujos(switch):
    salida = switch.ejecutar([f"table_dump {TABLA_FLUJOS}"])

    flujos = []
    actual = None

    for linea in salida.splitlines():
        if "default entry" in linea:
            break

        entrada = RE_ENTRADA.search(linea)
        if entrada:
            actual = {"handle": int(entrada.group(1), 16), "ips": []}
            flujos.append(actual)
            continue

        if actual is None:
            continue

        campo = RE_CAMPO_IP.search(linea)
        if campo:
            actual["ips"].append(hex_a_ip(campo.group(2)))
            continue

        accion = RE_ACCION.search(linea)
        if accion and "id" not in actual:
            datos = accion.group(1).replace(",", " ").split()
            if datos:
                actual["id"] = int(datos[0], 16)

    resultado = []
    for flujo in flujos:
        if len(flujo["ips"]) == 2 and "id" in flujo:
            resultado.append({
                "handle": flujo["handle"],
                "origen": flujo["ips"][0],
                "destino": flujo["ips"][1],
                "id": flujo["id"]
            })

    return sorted(resultado, key=lambda f: f["id"])


def leer_estadisticas(switch, flujos):
    comandos = [f"counter_read {CONTADOR_PROTOCOLO} {i}" for i in range(4)]
    comandos += [f"counter_read {CONTADOR_FLUJO} {f['handle']}" for f in flujos]
    comandos += [
        f"register_read {REG_BYTES}",
        f"register_read {REG_MINIMO}",
        f"register_read {REG_MAXIMO}",
        f"register_read {REG_ELEFANTE}",
        f"register_read {REG_HISTOGRAMA}",
        f"register_read {REG_UMBRAL}",
    ]

    salida = switch.ejecutar(comandos)

    protocolos = {}
    contadores_flujo = {}

    lecturas = [
        (nombre, indice, paquetes, cantidad)
        for nombre, indice, cantidad, paquetes
        in RE_CONTADOR_NUEVO.findall(salida)
    ]
    lecturas += RE_CONTADOR_ANTIGUO.findall(salida)

    for nombre, indice, paquetes, cantidad in lecturas:
        valor = {"paquetes": int(paquetes), "bytes": int(cantidad)}

        if nombre.endswith("proto_counter"):
            protocolos[PROTOCOLOS[int(indice)]] = valor
        elif nombre.endswith("flow_counter"):
            contadores_flujo[int(indice)] = valor

    registers = {}
    for linea in salida.splitlines():
        linea = linea.replace("RuntimeCmd:", "").strip()
        coincidencia = RE_REGISTER.match(linea)
        if coincidencia:
            nombre = coincidencia.group(1).split(".")[-1]
            valores = [int(v) for v in coincidencia.group(2).split(",")
                       if v.strip()]
            registers[nombre] = valores

    for clave in ("flow_bytes", "flow_pkt_min", "flow_pkt_max",
                  "flow_elephant", "size_hist", "elephant_threshold"):
        if clave not in registers:
            raise RuntimeError(f"No se pudo leer el register {clave}.")

    estadisticas_flujo = []
    for flujo in flujos:
        i = flujo["id"]
        contador = contadores_flujo.get(
            flujo["handle"], {"paquetes": 0, "bytes": 0}
        )
        estadisticas_flujo.append({
            **flujo,
            "paquetes": contador["paquetes"],
            "bytes": contador["bytes"],
            "bytes_register": registers["flow_bytes"][i],
            "minimo": registers["flow_pkt_min"][i],
            "maximo": registers["flow_pkt_max"][i],
            "marca_switch": registers["flow_elephant"][i] == 1,
        })

    return {
        "protocolos": protocolos,
        "flujos": estadisticas_flujo,
        "histograma": registers["size_hist"],
        "umbral_switch": registers["elephant_threshold"][0],
    }


def tasa(actual, anterior, clave, segundos):
    if anterior is None or segundos <= 0:
        return "-"
    diferencia = actual[clave] - anterior.get(clave, 0)
    return f"{formato_bytes(max(diferencia, 0) / segundos)}/s"


def imprimir(datos, anterior, segundos, umbral, lectura, args):
    if not args.sin_limpiar:
        print("\033[2J\033[H", end="")

    linea = "=" * 92
    print(linea)
    print(f" ESTADISTICAS DEL SWITCH s1  |  {ahora()}  |  "
          f"lectura #{lectura}  |  cada {args.intervalo:g} s")
    print(linea)

    print("\n TRAFICO POR PROTOCOLO (contador global proto_counter)")
    print(f" {'Protocolo':<10}{'Paquetes':>12}{'Bytes':>14}{'Tasa':>16}")
    print(" " + "-" * 52)

    total_paquetes = 0
    total_bytes = 0
    for nombre in PROTOCOLOS:
        valor = datos["protocolos"].get(nombre, {"paquetes": 0, "bytes": 0})
        previo = anterior["protocolos"].get(nombre) if anterior else None
        total_paquetes += valor["paquetes"]
        total_bytes += valor["bytes"]
        print(f" {nombre:<10}{valor['paquetes']:>12}{valor['bytes']:>14}"
              f"{tasa(valor, previo, 'bytes', segundos):>16}")

    print(" " + "-" * 52)
    print(f" {'TOTAL':<10}{total_paquetes:>12}{total_bytes:>14}")

    print("\n TRAFICO POR FLUJO (contador directo flow_counter + registers)")
    print(f" {'Origen':<11}{'Destino':<12}{'Paquetes':>9}{'Bytes':>11}"
          f"{'Min':>7}{'Max':>7}{'Prom':>7}{'Tasa':>14}  Estado")
    print(" " + "-" * 90)

    flujos_previos = {}
    if anterior:
        flujos_previos = {f["id"]: f for f in anterior["flujos"]}

    activos = 0
    for flujo in datos["flujos"]:
        if flujo["paquetes"] == 0 and not args.todos:
            continue

        activos += 1
        promedio = flujo["bytes"] // flujo["paquetes"] if flujo["paquetes"] else 0
        estado = "ELEFANTE" if es_elefante(flujo, umbral) else "normal"
        print(f" {flujo['origen']:<11}{flujo['destino']:<12}"
              f"{flujo['paquetes']:>9}{flujo['bytes']:>11}"
              f"{flujo['minimo']:>7}{flujo['maximo']:>7}{promedio:>7}"
              f"{tasa(flujo, flujos_previos.get(flujo['id']), 'bytes', segundos):>14}"
              f"  {estado}")

    if activos == 0:
        print(" (todavia no hay trafico registrado en los flujos)")

    print("\n TAMANO DE LOS PAQUETES (register size_hist)")
    total_hist = sum(datos["histograma"]) or 1
    for nombre, cantidad in zip(CATEGORIAS_TAMANO, datos["histograma"]):
        barra = "#" * int(30 * cantidad / total_hist)
        print(f" {nombre:<14}{cantidad:>8}  {barra}")

    print(f"\n Umbral de flujo elefante: {umbral} bytes "
          f"(register del switch: {datos['umbral_switch']})")
    print(f" Alertas registradas en: {BASE.name}/{ARCHIVO_ALERTAS.name}")
    print(" Ctrl+C para salir")
    sys.stdout.flush()


def es_elefante(flujo, umbral):
    return flujo["marca_switch"] or flujo["bytes"] > umbral


def revisar_elefantes(datos, umbral, ya_reportados, historial):
    alertas = []

    for flujo in datos["flujos"]:
        clave = (flujo["origen"], flujo["destino"])

        if es_elefante(flujo, umbral) and clave not in ya_reportados:
            ya_reportados.add(clave)
            historial.append(
                f"[{ahora()}] {flujo['origen']} -> {flujo['destino']}: "
                f"{flujo['bytes']} bytes > umbral {umbral}"
            )
            alertas.append(
                "\n".join([
                    "",
                    "!" * 50,
                    "ALERTA: Flujo elefante detectado",
                    "",
                    f"Fecha: {ahora()}",
                    f"Origen: {flujo['origen']}",
                    f"Destino: {flujo['destino']}",
                    f"Paquetes: {flujo['paquetes']}",
                    f"Bytes: {flujo['bytes']}",
                    f"Umbral: {umbral}",
                    "Marcado por el switch: "
                    + ("si" if flujo["marca_switch"] else "no"),
                    "!" * 50,
                ])
            )

    if alertas:
        try:
            with open(ARCHIVO_ALERTAS, "a") as archivo:
                for alerta in alertas:
                    archivo.write(alerta + "\n")
        except OSError as error:
            print(f"AVISO: no se pudo escribir {ARCHIVO_ALERTAS.name}: {error}")

    return alertas


def configurar(switch, args):
    comandos = []

    if args.reset:
        comandos += [
            f"counter_reset {CONTADOR_PROTOCOLO}",
            f"counter_reset {CONTADOR_FLUJO}",
            f"register_reset {REG_BYTES}",
            f"register_reset {REG_MINIMO}",
            f"register_reset {REG_MAXIMO}",
            f"register_reset {REG_HISTOGRAMA}",
            f"register_reset {REG_ELEFANTE}",
        ]

    salida = switch.ejecutar([f"register_read {REG_UMBRAL} 0"])
    coincidencia = re.search(r"\[0\]=\s*(\d+)", salida)
    umbral_actual = int(coincidencia.group(1)) if coincidencia else None

    if umbral_actual != args.umbral:
        comandos += [
            f"register_reset {REG_ELEFANTE}",
            f"register_write {REG_UMBRAL} 0 {args.umbral}",
        ]

    if not comandos:
        return

    salida = switch.ejecutar(comandos)

    if "Error" in salida:
        raise RuntimeError(f"Error configurando el switch:\n{salida}")


def leer_argumentos():
    parser = argparse.ArgumentParser(
        description="Lee periodicamente los contadores del switch P4."
    )
    parser.add_argument("--thrift-port", type=int, default=9090,
                        help="Puerto Thrift del switch (por defecto 9090)")
    parser.add_argument("--intervalo", type=float, default=5,
                        help="Segundos entre lecturas (maximo 5, por defecto 5)")
    parser.add_argument("--umbral", type=int, default=100000,
                        help="Umbral de flujo elefante en bytes")
    parser.add_argument("--reset", action="store_true",
                        help="Pone en cero contadores y registers al iniciar")
    parser.add_argument("--una-vez", action="store_true",
                        help="Hace una sola lectura y termina")
    parser.add_argument("--todos", action="store_true",
                        help="Muestra tambien los flujos sin trafico")
    parser.add_argument("--sin-limpiar", action="store_true",
                        help="No limpia la pantalla entre lecturas")

    args = parser.parse_args()

    if args.intervalo <= 0 or args.intervalo > 5:
        parser.error("El intervalo debe ser mayor que 0 y como maximo 5 s.")
    if args.umbral <= 0:
        parser.error("El umbral debe ser mayor que 0.")

    return args


def main():
    args = leer_argumentos()
    switch = SwitchThrift(args.thrift_port)

    try:
        configurar(switch, args)
        flujos = leer_flujos(switch)
    except RuntimeError as error:
        sys.exit(f"ERROR: {error}")

    if not flujos:
        sys.exit("ERROR: la tabla flow_stats no tiene flujos instalados.")

    anterior = None
    tiempo_anterior = None
    reportados = set()
    historial = []
    lectura = 0

    try:
        while True:
            inicio = time.monotonic()
            lectura += 1

            try:
                datos = leer_estadisticas(switch, flujos)
            except RuntimeError as error:
                print(f"[{ahora()}] ERROR: {error}")
                if args.una_vez:
                    sys.exit(1)
                time.sleep(args.intervalo)
                continue

            segundos = inicio - tiempo_anterior if tiempo_anterior else 0
            imprimir(datos, anterior, segundos, args.umbral, lectura, args)

            nuevas = revisar_elefantes(datos, args.umbral, reportados,
                                       historial)

            if historial:
                print("\n FLUJOS ELEFANTE DETECTADOS")
                for resumen in historial:
                    print(f"  {resumen}")

            for alerta in nuevas:
                print(alerta)

            sys.stdout.flush()

            if args.una_vez:
                break

            anterior = datos
            tiempo_anterior = inicio

            espera = args.intervalo - (time.monotonic() - inicio)
            time.sleep(max(espera, 0))

    except KeyboardInterrupt:
        print("\nControlador detenido.")


if __name__ == "__main__":
    main()