#!/usr/bin/env python3

import subprocess
import time

from pathlib import Path
from mininet.net import Mininet
from mininet.node import Switch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


BASE = Path(__file__).resolve().parent
JSON = BASE / "build" / "counters.json"
TABLES = BASE / "tables"

THRIFT_PORT = 9090

HOSTS = {
    "h1": ("10.0.0.1", "00:00:00:00:00:01", 1),
    "h2": ("10.0.0.2", "00:00:00:00:00:02", 2),
    "h3": ("10.0.0.3", "00:00:00:00:00:03", 3),
    "h4": ("10.0.0.4", "00:00:00:00:00:04", 4),
}


class P4Switch(Switch):
    def __init__(self, name, thrift_port, device_id, **kwargs):
        super().__init__(name, **kwargs)
        self.thrift_port = thrift_port
        self.device_id = device_id
        self.process = None
        self.log_file = None

    def start(self, controllers):
        command = [
            "simple_switch",
            "--device-id", str(self.device_id),
            "--thrift-port", str(self.thrift_port)
        ]

        for port, intf in sorted(self.intfs.items()):
            if port > 0 and intf is not None:
                command.extend(["-i", f"{port}@{intf.name}"])
                subprocess.run(
                    ["sysctl", "-q", "-w",
                     f"net.ipv6.conf.{intf.name}.disable_ipv6=1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )

        command.append(str(JSON))

        self.log_file = open(f"/tmp/{self.name}-p4.log", "w")

        self.process = subprocess.Popen(
            command,
            stdout=self.log_file,
            stderr=subprocess.STDOUT
        )

    def stop(self, deleteIntfs=True):
        if self.process is not None:
            self.process.terminate()

            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

        if self.log_file is not None:
            self.log_file.close()

        super().stop(deleteIntfs)


def esperar_thrift(puerto, intentos=20):
    for _ in range(intentos):
        resultado = subprocess.run(
            ["simple_switch_CLI", "--thrift-port", str(puerto)],
            input="show_tables\n",
            text=True,
            capture_output=True,
            timeout=15
        )
        if resultado.returncode == 0 and "ipv4_forward" in resultado.stdout:
            return
        time.sleep(0.5)

    raise RuntimeError("El switch no respondio por Thrift.")


def cargar_tablas(nombre, puerto):
    archivo = TABLES / f"{nombre}.txt"

    with open(archivo) as f:
        reglas = f.read()

    resultado = subprocess.run(
        ["simple_switch_CLI", "--thrift-port", str(puerto)],
        input=reglas,
        text=True,
        capture_output=True,
        timeout=15
    )

    salida = resultado.stdout + resultado.stderr

    if resultado.returncode != 0 or "Error" in salida:
        raise RuntimeError(
            f"Error configurando {nombre}:\n{salida}"
        )

    info(f"*** Tablas y umbral cargados en {nombre}\n")


def configurar_host(host, vecinos):
    interfaz = host.defaultIntf().name

    host.cmd("sysctl -q -w net.ipv6.conf.all.disable_ipv6=1")
    host.cmd("sysctl -q -w net.ipv6.conf.default.disable_ipv6=1")

    for opcion in ("rx", "tx", "sg"):
        host.cmd(f"ethtool --offload {interfaz} {opcion} off")

    for ip, mac in vecinos:
        host.cmd(
            f"ip neigh replace {ip} lladdr {mac} "
            f"dev {interfaz} nud permanent"
        )


def crear_red():
    if not JSON.exists():
        raise FileNotFoundError(
            "No existe build/counters.json. Compila counters.p4 primero."
        )

    net = Mininet(controller=None, build=False)

    info("*** Creando switch P4\n")
    s1 = net.addSwitch(
        "s1", cls=P4Switch, thrift_port=THRIFT_PORT, device_id=0
    )

    info("*** Creando hosts\n")
    for nombre, (ip, mac, puerto) in HOSTS.items():
        host = net.addHost(nombre, ip=f"{ip}/24", mac=mac)
        net.addLink(host, s1, port2=puerto)

    info("*** Iniciando la red\n")
    net.build()
    net.start()

    try:
        time.sleep(1)

        if s1.process.poll() is not None:
            raise RuntimeError(
                "s1 no pudo iniciar. Revisa /tmp/s1-p4.log"
            )

        esperar_thrift(THRIFT_PORT)

        info("*** Configurando hosts\n")
        for nombre, (ip, mac, _) in HOSTS.items():
            vecinos = [
                (otra_ip, otra_mac)
                for otro, (otra_ip, otra_mac, _) in HOSTS.items()
                if otro != nombre
            ]
            configurar_host(net.get(nombre), vecinos)

        info("*** Cargando tablas del switch\n")
        cargar_tablas("s1", THRIFT_PORT)

    except Exception:
        net.stop()
        raise

    return net


def ejecutar():
    net = crear_red()

    try:
        info("*** Red configurada\n")
        info("*** Controlador: python3 lab2-counters/controller.py\n")
        info("*** Iniciando consola Mininet\n")
        CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    ejecutar()
