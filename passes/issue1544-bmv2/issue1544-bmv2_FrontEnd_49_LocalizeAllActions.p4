#include <core.p4>
#include <v1model.p4>
struct metadata {
}
header ethernet_t {
    bit<48> dstAddr;
    bit<48> srcAddr;
    bit<16> etherType;
}
struct headers {
    ethernet_t ethernet;
}
parser ParserImpl(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    state start {
        packet.extract<ethernet_t>(hdr.ethernet);
        transition accept;
    }
}
control ingress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    @name(".my_drop") action my_drop_1(inout standard_metadata_t smeta_0) {
        mark_to_drop(smeta_0);
    }
    bit<16> tmp_0;
    @name("set_port") action set_port_0(bit<9> output_port) {
        standard_metadata.egress_spec = output_port;
    }
    @name("mac_da") table mac_da {
        key = {
            hdr.ethernet.dstAddr: exact @name("hdr.ethernet.dstAddr") ;
        }
        actions = {
            set_port_0();
            my_drop_1(standard_metadata);
        }
        default_action = my_drop_1(standard_metadata);
    }
    apply {
        mac_da.apply();
        {
            bit<16> x = hdr.ethernet.srcAddr[15:0];
            bool hasReturned_0 = false;
            bit<16> retval_0;
            if (x > 16w5) {
                hasReturned_0 = true;
                retval_0 = x + 16w65535;
            } else {
                hasReturned_0 = true;
                retval_0 = x;
            }
            tmp_0 = retval_0;
        }
        hdr.ethernet.srcAddr[15:0] = tmp_0;
    }
}
control egress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    apply {
    }
}
control DeparserImpl(packet_out packet, in headers hdr) {
    apply {
        packet.emit<ethernet_t>(hdr.ethernet);
    }
}
control verifyChecksum(inout headers hdr, inout metadata meta) {
    apply {
    }
}
control computeChecksum(inout headers hdr, inout metadata meta) {
    apply {
    }
}
V1Switch<headers, metadata>(ParserImpl(), verifyChecksum(), ingress(), egress(), computeChecksum(), DeparserImpl()) main;