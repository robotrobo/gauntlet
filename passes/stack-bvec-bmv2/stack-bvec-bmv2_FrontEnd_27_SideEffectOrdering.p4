#include <core.p4>
#include <v1model.p4>
struct alt_t {
    bit<1> valid;
    bit<7> port;
}
struct row_t {
    alt_t alt0;
    alt_t alt1;
}
header hdr {
    bit<32> f;
    row_t   row;
}
control compute(inout hdr h) {
    hdr[1] tmp_0;
    apply {
        {
            tmp_0[0].row.alt1.valid = 1w1;
        }
        {
            tmp_0[0].f = h.f + 32w1;
        }
        {
            h.f = tmp_0[0].f;
        }
        {
            tmp_0[0].row.alt0.port = h.row.alt0.port + 7w1;
        }
        {
            h.row.alt1.valid = tmp_0[0].row.alt1.valid;
        }
    }
}
struct Headers {
    hdr h;
}
struct Meta {
}
parser p(packet_in b, out Headers h, inout Meta m, inout standard_metadata_t sm) {
    state start {
        {
            b.extract<hdr>(h.h);
        }
        transition accept;
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
            b.emit<hdr>(h.h);
        }
    }
}
control ingress(inout Headers h, inout Meta m, inout standard_metadata_t sm) {
    @name("c") compute() c_0;
    apply {
        {
            c_0.apply(h.h);
        }
        {
            sm.egress_spec = 9w0;
        }
    }
}
V1Switch<Headers, Meta>(p(), vrfy(), ingress(), egress(), update(), deparser()) main;