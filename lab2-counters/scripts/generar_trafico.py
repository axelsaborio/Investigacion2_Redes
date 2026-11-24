#!/usr/bin/env python3

import argparse
import random
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")

from scapy.all import Ether, IP, TCP, UDP, ICMP, Raw, sendp, get_if_list, get_if_hwaddr


ENCABEZADOS = {
    "tcp": 14 + 20 + 20,
    "udp": 14 + 20 + 8,
    "icmp": 14 + 20 + 8,
    "otros": 14 + 20,
}

PROTOCOLO_EXPERIMENTAL = 253

TAMANO_MINIMO = 64
TAMANO_MAXIMO = 1500


def interfaz_del_host():
    for nombre in get_if_list():
        if nombre != "lo":
            return nombre
    sys.exit("ERROR: no se encontro una interfaz de red.")


def mac_destino(ip, interfaz):
    salida = subprocess.run(
        ["ip", "neigh", "show", ip, "dev", interfaz],
        capture_output=True, text=True
    ).stdout.split()

    if "lladdr" in salida:
        return salida[salida.index("lladdr") + 1]

    sys.exit(f"ERROR: no hay entrada ARP para {ip}. "
             "¿Se ejecuto la topologia del laboratorio?")


def crear_paquete(tipo, origen_mac, destino_mac, destino_ip, tamano):
    relleno = Raw(load=b"\x00" * (tamano - ENCABEZADOS[tipo]))
    base = Ether(src=origen_mac, dst=destino_mac) / IP(dst=destino_ip)

    if tipo == "tcp":
        capa = TCP(sport=random.randint(20000, 60000), dport=5001, flags="S")
    elif tipo == "udp":
        capa = UDP(sport=random.randint(20000, 60000), dport=5005)
    elif tipo == "icmp":
        capa = ICMP(type=8, id=random.randint(1, 65535))
    else:
        base[IP].proto = PROTOCOLO_EXPERIMENTAL
        return base / relleno

    return base / capa / relleno


def enviar(tipo, cantidad, tamano, args, origen_mac, destino_mac):
    paquetes = [
        crear_paquete(tipo, origen_mac, destino_mac, args.destino, tamano)
        for _ in range(cantidad)
    ]

    for paquete in paquetes:
        assert len(paquete) == tamano, "Tamano de paquete incorrecto"

    sendp(paquetes, iface=args.iface, inter=args.pausa, verbose=False)

    return {"tipo": tipo, "paquetes": cantidad, "bytes": cantidad * tamano}


def leer_argumentos():
    parser = argparse.ArgumentParser(
        description="Genera trafico controlado para el laboratorio 2."
    )
    parser.add_argument("--destino", required=True,
                        help="IP del host destino, por ejemplo 10.0.0.2")
    parser.add_argument("--tipo", default="mixto",
                        choices=["tcp", "udp", "icmp", "otros",
                                 "mixto", "elefante"],
                        help="Tipo de trafico a generar")
    parser.add_argument("--cantidad", type=int, default=10,
                        help="Paquetes por protocolo (por defecto 10)")
    parser.add_argument("--tamano", type=int, default=None,
                        help="Tamano de cada trama en bytes "
                             "(200 por defecto, 1000 en modo elefante)")
    parser.add_argument("--bytes", type=int, default=150000,
                        help="Bytes totales del flujo elefante")
    parser.add_argument("--pausa", type=float, default=0.002,
                        help="Segundos entre paquetes (por defecto 0.002)")
    parser.add_argument("--iface", default=None,
                        help="Interfaz de salida (se detecta sola)")

    args = parser.parse_args()

    if args.tamano is None:
        args.tamano = 1000 if args.tipo == "elefante" else 200

    if not TAMANO_MINIMO <= args.tamano <= TAMANO_MAXIMO:
        parser.error(f"El tamano debe estar entre {TAMANO_MINIMO} "
                     f"y {TAMANO_MAXIMO} bytes.")
    if args.cantidad <= 0 or args.bytes <= 0:
        parser.error("La cantidad y los bytes deben ser positivos.")

    return args


def main():
    args = leer_argumentos()

    if args.iface is None:
        args.iface = interfaz_del_host()

    origen_mac = get_if_hwaddr(args.iface)
    destino_mac = mac_destino(args.destino, args.iface)

    resultados = []

    if args.tipo == "mixto":
        for tipo in ("tcp", "udp", "icmp", "otros"):
            resultados.append(enviar(tipo, args.cantidad, args.tamano,
                                     args, origen_mac, destino_mac))

    elif args.tipo == "elefante":
        cantidad = -(-args.bytes // args.tamano)
        resultado = enviar("udp", cantidad, args.tamano,
                           args, origen_mac, destino_mac)
        resultado["tipo"] = "udp (elefante)"
        resultados.append(resultado)

    else:
        resultados.append(enviar(args.tipo, args.cantidad, args.tamano,
                                 args, origen_mac, destino_mac))

    print("=" * 50)
    print(f" TRAFICO ENVIADO  {args.iface} -> {args.destino}")
    print("=" * 50)
    print(f" {'Tipo':<16}{'Paquetes':>10}{'Bytes':>12}")
    print(" " + "-" * 38)

    total_paquetes = 0
    total_bytes = 0
    for r in resultados:
        total_paquetes += r["paquetes"]
        total_bytes += r["bytes"]
        print(f" {r['tipo']:<16}{r['paquetes']:>10}{r['bytes']:>12}")

    print(" " + "-" * 38)
    print(f" {'TOTAL':<16}{total_paquetes:>10}{total_bytes:>12}")
    print("=" * 50)


if __name__ == "__main__":
    main()
