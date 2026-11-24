#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x0800;

const bit<8> PROTO_ICMP = 1;
const bit<8> PROTO_TCP  = 6;
const bit<8> PROTO_UDP  = 17;

const bit<32> IDX_TCP   = 0;
const bit<32> IDX_UDP   = 1;
const bit<32> IDX_ICMP  = 2;
const bit<32> IDX_OTROS = 3;

#define MAX_FLUJOS 64

const bit<32> LIMITE_PEQUENO = 128;
const bit<32> LIMITE_MEDIANO = 512;
const bit<32> LIMITE_GRANDE  = 1024;

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

struct headers {
    ethernet_t ethernet;
    ipv4_t     ipv4;
}

struct metadata {
    bit<32> flow_id;
    bit<1>  flujo_registrado;
}

parser MyParser(
    packet_in packet,
    out headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);

        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4: parse_ipv4;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition accept;
    }
}

control MyVerifyChecksum(
    inout headers hdr,
    inout metadata meta
) {
    apply {
    }
}

control MyIngress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    counter(4, CounterType.packets_and_bytes) proto_counter;

    direct_counter(CounterType.packets_and_bytes) flow_counter;

    register<bit<64>>(MAX_FLUJOS) flow_bytes;

    register<bit<32>>(MAX_FLUJOS) flow_pkt_min;
    register<bit<32>>(MAX_FLUJOS) flow_pkt_max;

    register<bit<8>>(MAX_FLUJOS) flow_elephant;

    register<bit<64>>(4) size_hist;

    register<bit<64>>(1) elephant_threshold;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action forward(egressSpec_t port) {
        standard_metadata.egress_spec = port;
    }

    action count_flow(bit<32> flow_id) {
        flow_counter.count();
        meta.flow_id = flow_id;
        meta.flujo_registrado = 1;
    }

    action flujo_no_registrado() {
        flow_counter.count();
        meta.flujo_registrado = 0;
    }

    table ipv4_forward {
        key = {
            hdr.ipv4.dstAddr: exact;
        }

        actions = {
            forward;
            drop;
        }

        size = 64;
        default_action = drop();
    }

    table flow_stats {
        key = {
            hdr.ipv4.srcAddr: exact;
            hdr.ipv4.dstAddr: exact;
        }

        actions = {
            count_flow;
            flujo_no_registrado;
        }

        counters = flow_counter;
        size = MAX_FLUJOS;
        default_action = flujo_no_registrado();
    }

    action contar_protocolo(bit<32> indice) {
        proto_counter.count(indice);
    }

    apply {
        bit<32> tamano = standard_metadata.packet_length;

        if (hdr.ipv4.isValid()) {
            if (hdr.ipv4.protocol == PROTO_TCP) {
                contar_protocolo(IDX_TCP);
            } else if (hdr.ipv4.protocol == PROTO_UDP) {
                contar_protocolo(IDX_UDP);
            } else if (hdr.ipv4.protocol == PROTO_ICMP) {
                contar_protocolo(IDX_ICMP);
            } else {
                contar_protocolo(IDX_OTROS);
            }
        } else {
            contar_protocolo(IDX_OTROS);
        }

        bit<32> bucket;

        if (tamano < LIMITE_PEQUENO) {
            bucket = 0;
        } else if (tamano < LIMITE_MEDIANO) {
            bucket = 1;
        } else if (tamano < LIMITE_GRANDE) {
            bucket = 2;
        } else {
            bucket = 3;
        }

        bit<64> cantidad_bucket;
        size_hist.read(cantidad_bucket, bucket);
        size_hist.write(bucket, cantidad_bucket + 1);

        if (!hdr.ipv4.isValid()) {
            drop();
            return;
        }

        flow_stats.apply();

        if (meta.flujo_registrado == 1) {
            bit<64> bytes_flujo;
            flow_bytes.read(bytes_flujo, meta.flow_id);
            bytes_flujo = bytes_flujo + (bit<64>) tamano;
            flow_bytes.write(meta.flow_id, bytes_flujo);

            bit<32> minimo;
            flow_pkt_min.read(minimo, meta.flow_id);
            if (minimo == 0 || tamano < minimo) {
                flow_pkt_min.write(meta.flow_id, tamano);
            }

            bit<32> maximo;
            flow_pkt_max.read(maximo, meta.flow_id);
            if (tamano > maximo) {
                flow_pkt_max.write(meta.flow_id, tamano);
            }

            bit<64> umbral;
            elephant_threshold.read(umbral, 0);
            if (umbral != 0 && bytes_flujo > umbral) {
                flow_elephant.write(meta.flow_id, 1);
            }
        }

        ipv4_forward.apply();
    }
}

control MyEgress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    apply {
    }
}

control MyComputeChecksum(
    inout headers hdr,
    inout metadata meta
) {
    apply {
    }
}

control MyDeparser(
    packet_out packet,
    in headers hdr
) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
    }
}

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
