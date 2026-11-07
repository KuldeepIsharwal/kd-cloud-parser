# Subnet plan for 10.20.0.0/16 (Task 5)

Rule: allocate from the largest requirement to the smallest, start at 10.20.0.0, place each
subnet right after the previous one, and use the smallest prefix whose usable host count
(2^(32-prefix) - 2) is at least the requirement.

## Working

| Subnet | Hosts needed | Smallest block that fits | Prefix | Block size | Usable = size - 2 |
|---|---:|---|---:|---:|---:|
| app | 1,000 | 2^10 = 1024 (2^9 - 2 = 510 is too small) | /22 | 1024 | 1022 |
| public | 250 | 2^8 = 256 (2^7 - 2 = 126 is too small) | /24 | 256 | 254 |
| data | 100 | 2^7 = 128 (2^6 - 2 = 62 is too small) | /25 | 128 | 126 |
| management | 20 | 2^5 = 32 (2^4 - 2 = 14 is too small) | /27 | 32 | 30 |

Placement (each block starts right after the previous broadcast address; every start is
aligned to its own block size, so no gaps are needed):

1. **app** /22 starts at 10.20.0.0. 1024 addresses = 4 × 256, so it covers 10.20.0.0 – 10.20.3.255.
2. **public** /24 starts at the next address, 10.20.4.0, and covers 10.20.4.0 – 10.20.4.255.
3. **data** /25 starts at 10.20.5.0 and covers 128 addresses: 10.20.5.0 – 10.20.5.127.
4. **management** /27 starts at 10.20.5.128 (128 is a multiple of 32) and covers 32 addresses: 10.20.5.128 – 10.20.5.159.

Total used: 1024 + 256 + 128 + 32 = 1440 addresses; 10.20.5.160 – 10.20.255.255 stays free.

## Result

| Subnet | Network address | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---|---:|---|---|---:|
| app | 10.20.0.0 | /22 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

These values were checked with Python's `ipaddress` module (`network/check_subnets.py`).
