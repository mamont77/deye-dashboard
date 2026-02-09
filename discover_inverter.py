#!/usr/bin/env python3
"""Auto-discover Deye inverters on the local network.

Scans the local /24 subnet for devices with port 8899 open (Solarman V5
protocol), then attempts to identify them via the Wi-Fi module discovery
protocol (UDP 48899).

Can be run standalone or imported by deploy_local.sh via --json flag.
"""

import socket
import sys
import threading
import json
import netifaces


SOLARMAN_PORT = 8899
SCAN_TIMEOUT = 1.0   # seconds per TCP port probe
PROBE_TIMEOUT = 3    # seconds for UDP identification probe

# Interface prefixes to skip (VPNs, tunnels, Docker, etc.)
SKIP_IFACE_PREFIXES = ("utun", "tun", "tap", "docker", "br-", "veth", "awdl", "llw")


def get_local_subnets():
    """Return a list of (prefix, local_ip) from physical network interfaces."""
    subnets = []
    seen_prefixes = set()
    for iface in netifaces.interfaces():
        # Skip loopback, VPN tunnels, and virtual interfaces
        if iface == "lo" or iface == "lo0":
            continue
        if any(iface.startswith(p) for p in SKIP_IFACE_PREFIXES):
            continue

        addrs = netifaces.ifaddresses(iface)
        if netifaces.AF_INET in addrs:
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get("addr", "")
                if ip.startswith("127."):
                    continue
                parts = ip.split(".")
                if len(parts) == 4:
                    prefix = ".".join(parts[:3])
                    if prefix not in seen_prefixes:
                        seen_prefixes.add(prefix)
                        subnets.append((prefix, ip))
    return subnets


def scan_port(ip, port, timeout, results, lock):
    """Try to connect to ip:port; append ip to results on success."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        with lock:
            results.append(ip)
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass


def scan_subnet(prefix, port=SOLARMAN_PORT, timeout=SCAN_TIMEOUT):
    """Scan a /24 subnet for hosts with the given port open."""
    results = []
    lock = threading.Lock()
    threads = []
    for i in range(1, 255):
        ip = f"{prefix}.{i}"
        t = threading.Thread(target=scan_port, args=(ip, port, timeout, results, lock))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=SCAN_TIMEOUT + 1)
    results.sort(key=lambda ip: list(map(int, ip.split("."))))
    return results


def probe_solarman(ip, timeout=PROBE_TIMEOUT):
    """Try to identify a Solarman logger via UDP discovery (port 48899).

    The HF-A11ASSISTHREAD command is the standard Wi-Fi module identification
    protocol. Response format is "IP,MAC,MODEL" comma-separated.

    Returns a dict with device info. Always includes 'ip'.
    """
    info = {"ip": ip, "serial": None, "model": None}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"HF-A11ASSISTHREAD", (ip, 48899))
        data, _ = sock.recvfrom(1024)
        sock.close()
        decoded = data.decode("utf-8", errors="replace").strip()
        parts = decoded.split(",")
        if len(parts) >= 3:
            info["model"] = parts[2]
        if len(parts) >= 2:
            info["mac"] = parts[1]
    except Exception:
        pass
    return info


def discover(quiet=False):
    """Run the full discovery process. Returns list of found devices."""
    subnets = get_local_subnets()
    if not subnets:
        if not quiet:
            print("Could not determine local network subnets.")
        return []

    if not quiet:
        subnet_strs = ", ".join(f"{p}.0/24" for p, _ in subnets)
        print(f"Scanning subnets: {subnet_strs}")
        print(f"Looking for devices with port {SOLARMAN_PORT} open...\n")

    all_found = []
    for prefix, local_ip in subnets:
        if not quiet:
            print(f"  Scanning {prefix}.0/24 ...", end=" ", flush=True)
        hosts = scan_subnet(prefix)
        if not quiet:
            print(f"found {len(hosts)} device(s)")
        all_found.extend(hosts)

    if not all_found:
        if not quiet:
            print("\nNo devices with port 8899 found on the local network.")
        return []

    if not quiet:
        print(f"\nFound {len(all_found)} device(s) with port {SOLARMAN_PORT} open.")
        print("Probing for Solarman/Deye identification...\n")

    devices = []
    for ip in all_found:
        if not quiet:
            print(f"  Probing {ip} ...", end=" ", flush=True)
        info = probe_solarman(ip)
        devices.append(info)
        if not quiet:
            model = info.get("model") or "unknown model"
            print(model)

    return devices


def main():
    """CLI entry point — discover and print results."""
    json_mode = "--json" in sys.argv

    devices = discover(quiet=json_mode)

    if json_mode:
        print(json.dumps(devices))
        return

    if not devices:
        print("\nNo Deye/Solarman inverters found.")
        print("Make sure you are on the same network as your inverter.")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f" Found {len(devices)} Deye/Solarman device(s):")
    print(f"{'='*50}")
    for i, dev in enumerate(devices, 1):
        model = dev.get("model") or "Unknown"
        serial = dev.get("serial") or "Not detected"
        print(f"  [{i}] IP: {dev['ip']}  |  Model: {model}  |  Serial: {serial}")
    print()


if __name__ == "__main__":
    main()
