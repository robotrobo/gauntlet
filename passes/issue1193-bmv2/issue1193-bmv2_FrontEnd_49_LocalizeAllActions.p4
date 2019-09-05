#include <core.p4>
#include <v1model.p4>
extern jnf_counter {
    jnf_counter(CounterType type);
    void count();
}
struct metadata {
}
struct headers {
}
parser MyParser(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    state start {
        transition accept;
    }
}
control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {
    }
}
control MyIngress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    @name(".NoAction") action NoAction_1() {
    }
    @name("c") jnf_counter(CounterType.packets) c;
    @name("a") action a_0() {
        c.count();
    }
    @name("t") table t {
        actions = {
            a_0();
            @defaultonly NoAction_1();
        }
        default_action = NoAction_1();
    }
    apply {
        t.apply();
    }
}
control MyEgress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    apply {
    }
}
control MyDeparser(packet_out packet, in headers hdr) {
    apply {
    }
}
control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply {
    }
}
V1Switch<headers, metadata>(MyParser(), MyVerifyChecksum(), MyIngress(), MyEgress(), MyComputeChecksum(), MyDeparser()) main;