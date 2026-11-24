# Investigación 2 - Redes Programables con P4

Proyecto del curso CI-0121 Redes de Comunicación de Datos de la Universidad de Costa Rica.

## Descripción

El proyecto consiste en desarrollar aplicaciones de redes programables utilizando el lenguaje P4, BMv2 y Mininet.

Se incluyen dos laboratorios independientes:

- Laboratorio 1: Router IPv4 estático.
- Laboratorio 2: Contadores y estadísticas de tráfico.

## Herramientas utilizadas

- Ubuntu 24.04 LTS
- P4C
- BMv2
- Mininet 2.3.0
- Python 3
- Scapy
- iperf3

## Laboratorio 1 - Router IPv4 estático

### Descripción

Implementación de un router IPv4 programable mediante P4 y BMv2.

El programa permite:

- Analizar encabezados Ethernet e IPv4.
- Realizar enrutamiento mediante Longest Prefix Match (LPM).
- Decrementar el TTL de los paquetes.
- Descartar paquetes cuyo TTL sea insuficiente.
- Reescribir las direcciones MAC de origen y destino.
- Descartar paquetes sin una ruta disponible.
- Actualizar el checksum IPv4.

### Topología

La red utiliza tres routers P4 y cuatro hosts distribuidos en subredes diferentes.

| Host | Dirección IP | Gateway |
|------|-------------|---------|
| h1 | 10.0.1.10/24 | 10.0.1.1 |
| h2 | 10.0.2.10/24 | 10.0.2.1 |
| h3 | 10.0.3.10/24 | 10.0.3.1 |
| h4 | 10.0.4.10/24 | 10.0.4.1 |

Los routers están conectados de la siguiente manera:

- s1 conecta h1, h2 y s2.
- s2 conecta s1, h3 y s3.
- s3 conecta s2 y h4.

### Estructura del laboratorio

- router.p4: implementación del router IPv4.
- topology.py: creación y configuración de la red Mininet.
- tables/: archivos de configuración de las tablas LPM.
- scripts/pruebas.sh: verificaciones iniciales del laboratorio.
- build/: archivos generados durante la compilación.

### Compilación

Desde la raíz del repositorio:

```bash
mkdir -p lab1-router/build

p4c-bm2-ss --arch v1model \
-o lab1-router/build/router.json \
lab1-router/router.p4
```

### Ejecución

Limpiar las configuraciones anteriores:

```bash
sudo mn -c
```

Iniciar la topología:

```bash
sudo python3 lab1-router/topology.py
```

El programa inicia tres switches BMv2, configura los hosts y carga las tablas de enrutamiento.

### Pruebas

#### 1. Conectividad

Dentro de Mininet:

```bash
pingall
```

Resultado obtenido:

12 de 12 pruebas exitosas, con 0 % de pérdida.

#### 2. Decremento del TTL

```bash
h1 ping -c 3 -t 64 10.0.4.10
```

Los paquetes atraviesan tres routers.

Mediante una captura con Scapy en h4, se verificó que los paquetes enviados desde h1 llegan con TTL = 61.

#### 3. Descarte por TTL insuficiente

```bash
h1 ping -c 3 -W 1 -t 2 10.0.4.10
```

Resultado obtenido:

3 paquetes transmitidos, 0 recibidos y 100 % de pérdida.

#### 4. Descarte por ausencia de ruta

```bash
h1 ping -c 3 -W 1 10.0.5.10
```

Resultado obtenido:

3 paquetes transmitidos, 0 recibidos y 100 % de pérdida.

Se verificó mediante simple_switch_CLI que la tabla de s1 no contiene una ruta hacia 10.0.5.10 y que su acción predeterminada es drop.

#### 5. Inspección de tablas

Desde otra terminal, con Mininet ejecutándose:

```bash
echo "table_dump ipv4_lpm" | sudo simple_switch_CLI --thrift-port 9091
```

El comando permite consultar las rutas instaladas en s1.

### Script de verificación

Desde la raíz del repositorio:

```bash
./lab1-router/scripts/pruebas.sh
```

El script comprueba:

- Compilación del programa P4.
- Sintaxis del programa de Mininet.
- Existencia de las tablas de enrutamiento.
- Cantidad de rutas configuradas.

Las pruebas de conectividad y comportamiento de los paquetes se ejecutan por separado dentro de Mininet.

### Finalización

Para salir de Mininet:

```bash
exit
```

Si es necesario limpiar la red:

```bash
sudo mn -c
```

## Laboratorio 2 - Contadores y estadísticas de tráfico

### Descripción

Sistema de monitoreo de tráfico en el plano de datos con P4 y BMv2.

El programa permite:

- Contar paquetes y bytes por flujo (IP origen + IP destino) con contadores directos.
- Contar paquetes y bytes por protocolo: TCP, UDP, ICMP y otros.
- Registrar el tamaño de los paquetes mediante registers (bytes por flujo, tamaño mínimo y máximo, histograma).
- Consultar las estadísticas desde un controlador Python cada 5 segundos.
- Detectar flujos elefante con un umbral configurable de bytes.

### Topología

Un switch P4 (s1) con cuatro hosts en la subred 10.0.0.0/24:

| Host | Dirección IP | Puerto de s1 |
|------|-------------|--------------|
| h1 | 10.0.0.1/24 | 1 |
| h2 | 10.0.0.2/24 | 2 |
| h3 | 10.0.0.3/24 | 3 |
| h4 | 10.0.0.4/24 | 4 |

### Compilación

Desde la raíz del repositorio:

```bash
mkdir -p lab2-counters/build

p4c-bm2-ss --arch v1model \
-o lab2-counters/build/counters.json \
lab2-counters/counters.p4
```

### Ejecución

Terminal 1:

```bash
sudo mn -c
sudo python3 lab2-counters/topology.py
```

Terminal 2:

```bash
python3 lab2-counters/controller.py --reset
```

Dentro de Mininet, para generar tráfico:

```bash
h1 python3 lab2-counters/scripts/generar_trafico.py --destino 10.0.0.2 --tipo mixto
h1 python3 lab2-counters/scripts/generar_trafico.py --destino 10.0.0.3 --tipo elefante --bytes 150000
```

### Pruebas

```bash
./lab2-counters/scripts/pruebas.sh
./lab2-counters/scripts/pruebas.sh --completo
```

La opción `--completo` ejecuta las 6 pruebas del laboratorio en Mininet y compara el tráfico generado con los valores de los contadores. Resultado obtenido: 22/22 comprobaciones correctas.

La documentación completa está en `lab2-counters/README.md`.

## Informe

El informe de investigación se encuentra en la carpeta informe/.

## Video demostrativo

El video demostrativo mostrará el funcionamiento de las implementaciones y sus respectivas pruebas.
