#include <core.p4>
#include <v1model.p4>

header ethernet_t {
    bit<48> dst_addr;
    bit<48> src_addr;
    bit<16> eth_type;
}

struct Headers {
    ethernet_t    eth_hdr;
}

struct Meta {
}

bit<48> do_thing(inout bit<16> val_0) {
    if (val_0 >= 16w2) {
        val_0 = 16w0;
    } else {
        val_0 = 16w1;
    }
    return 2;
}
control ingress(inout Headers h, inout Meta m, inout standard_metadata_t sm) {
    apply {
        h.eth_hdr.dst_addr = do_thing(h.eth_hdr.eth_type);
    }
}

parser p(packet_in b, out Headers h, inout Meta m, inout standard_metadata_t sm) {
state start {transition accept;}}

control vrfy(inout Headers h, inout Meta m) { apply {} }

control update(inout Headers h, inout Meta m) { apply {} }

control egress(inout Headers h, inout Meta m, inout standard_metadata_t sm) { apply {} }

control deparser(packet_out b, in Headers h) { apply {} }

V1Switch(p(), vrfy(), ingress(), egress(), update(), deparser()) main;

