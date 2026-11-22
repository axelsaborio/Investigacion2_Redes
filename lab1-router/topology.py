#!/usr/bin/env python3

import os
import subprocess
import time

from pathlib import Path
from mininet.net import Mininet
from mininet.node import Switch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


BASE = Path(__file__).resolve().parent
JSON = BASE / "build" / "router.json"
TABLES = BASE / "tables"


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

    if resultado.returncode != 0 or "Error:" in salida:
        raise RuntimeError(
            f"Error configurando {nombre}:\n{salida}"
        )

    info(f"*** Tabla cargada en {nombre}\n")


def configurar_host(host, gateway, mac_gateway):
    interfaz = host.defaultIntf().name

    host.cmd(f"ip route replace default via {gateway}")

    host.cmd(
        f"ip neigh replace {gateway} "
        f"lladdr {mac_gateway} "
        f"dev {interfaz} nud permanent"
    )


def ejecutar():
    if not JSON.exists():
        raise FileNotFoundError(
            "No existe router.json. Compila router.p4 primero."
        )

    net = Mininet(controller=None, build=False)

    info("*** Creando routers P4\n")

    s1 = net.addSwitch("s1", cls=P4Switch, thrift_port=9091, device_id=1)
    s2 = net.addSwitch("s2", cls=P4Switch, thrift_port=9092, device_id=2)
    s3 = net.addSwitch("s3", cls=P4Switch, thrift_port=9093, device_id=3)
	
    info("*** Creando hosts\n")

    h1 = net.addHost(
        "h1", ip="10.0.1.10/24",
        mac="00:00:00:00:01:01"
    )

    h2 = net.addHost(
        "h2", ip="10.0.2.10/24",
        mac="00:00:00:00:02:02"
    )

    h3 = net.addHost(
        "h3", ip="10.0.3.10/24",
        mac="00:00:00:00:03:03"
    )

    h4 = net.addHost(
        "h4", ip="10.0.4.10/24",
        mac="00:00:00:00:04:04"
    )

    info("*** Creando enlaces\n")

    net.addLink(h1, s1, port2=1)
    net.addLink(h2, s1, port2=2)

    net.addLink(s1, s2, port1=3, port2=1)

    net.addLink(h3, s2, port2=2)

    net.addLink(s2, s3, port1=3, port2=1)

    net.addLink(h4, s3, port2=2)

    try:
        info("*** Iniciando la red\n")

        net.build()
        net.start()

        time.sleep(2)

        for switch in (s1, s2, s3):
            if switch.process.poll() is not None:
                raise RuntimeError(
                    f"{switch.name} no pudo iniciar. "
                    f"Revisa /tmp/{switch.name}-p4.log"
                )

        info("*** Configurando gateways\n")

        configurar_host(
            h1, "10.0.1.1", "00:aa:00:00:01:01"
        )

        configurar_host(
            h2, "10.0.2.1", "00:aa:00:00:01:02"
        )

        configurar_host(
            h3, "10.0.3.1", "00:aa:00:00:02:02"
        )

        configurar_host(
            h4, "10.0.4.1", "00:aa:00:00:03:02"
        )

        info("*** Cargando tablas de enrutamiento\n")

        cargar_tablas("s1", 9091)
        cargar_tablas("s2", 9092)
        cargar_tablas("s3", 9093)

        info("*** Red configurada\n")
        info("*** Iniciando consola Mininet\n")

        CLI(net)

    finally:
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    ejecutar()
