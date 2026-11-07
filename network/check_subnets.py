"""Recompute the subnet table in network/subnets.md with the standard library."""
import ipaddress
import math

NEEDS = [("app", 1000), ("public", 250), ("data", 100), ("management", 20)]


def plan(base="10.20.0.0/16", needs=NEEDS):
    cur = ipaddress.ip_network(base).network_address
    rows = []
    for name, hosts in sorted(needs, key=lambda x: -x[1]):
        prefix = 32 - math.ceil(math.log2(hosts + 2))
        net = ipaddress.ip_network(f"{cur}/{prefix}")
        hosts_list = list(net.hosts())
        rows.append((name, str(net.network_address), prefix, f"{hosts_list[0]} - {hosts_list[-1]}",
                     str(net.broadcast_address), 2 ** (32 - prefix) - 2))
        cur = net.broadcast_address + 1
    return rows


if __name__ == "__main__":
    for r in plan():
        print("{:<11} {:<12} /{:<3} {:<28} {:<13} {}".format(*r))
