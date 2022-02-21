import ipaddress


def ip_is_local(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except:
        return False
    networks = [
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
        '0.0.0.0/8',
        '100.64.0.0/10',
        '127.0.0.0/8',
        '169.254.0.0/16',
        '192.0.0.0/24',
        '192.0.2.0/24',
        '192.88.99.0/24',
        '198.18.0.0/15',
        '198.51.100.0/24',
        '203.0.113.0/24',
        '224.0.0.0/4',
        '233.252.0.0/24',
        '240.0.0.0/4',
        '255.255.255.255/32'
    ]
    for network in networks:
        if addr in ipaddress.ip_network(network):
            return True
    return False