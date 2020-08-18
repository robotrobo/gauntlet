#include <core.p4>
#define V1MODEL_VERSION 20180101
#include <v1model.p4>

header ethernet_t {
    bit<48> dst_addr;
    bit<48> src_addr;
    bit<16> eth_type;
}

struct Headers {
    ethernet_t eth_hdr;
}

struct Meta {
}

parser p(packet_in pkt, out Headers hdr, inout Meta m, inout standard_metadata_t sm) {
    state start {
        pkt.extract<ethernet_t>(hdr.eth_hdr);
        transition accept;
    }
}

control ingress(inout Headers h, inout Meta m, inout standard_metadata_t sm) {
    bool hasReturned;
    ethernet_t val_eth_hdr;
    @name("ingress.simple_action") action simple_action() {
        hasReturned = false;
        {
            bool cond;
            cond = h.eth_hdr.eth_type == 16w1;
            hasReturned = (cond ? true : hasReturned);
        }
        {
            bool cond_0;
            cond_0 = !hasReturned;
            {
                val_eth_hdr = (cond_0 ? h.eth_hdr : val_eth_hdr);
            }
            h.eth_hdr.src_addr = (cond_0 ? 48w1 : h.eth_hdr.src_addr);
            h.eth_hdr = (cond_0 ? val_eth_hdr : h.eth_hdr);
        }
    }
    apply {
        h.eth_hdr.src_addr = 48w2;
        h.eth_hdr.dst_addr = 48w2;
        h.eth_hdr.eth_type = 16w2;
        simple_action();
    }
}

control vrfy(inout Headers h, inout Meta m) {
    apply {
    }
}

control update(inout Headers h, inout Meta m) {
    apply {
    }
}

control egress(inout Headers h, inout Meta m, inout standard_metadata_t sm) {
    apply {
    }
}

control deparser(packet_out b, in Headers h) {
    apply {
        {
            b.emit<ethernet_t>(h.eth_hdr);
        }
    }
}

V1Switch<Headers, Meta>(p(), vrfy(), ingress(), egress(), update(), deparser()) main;

