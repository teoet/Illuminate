#!/usr/bin/env python3
"""
udp_listener is simulating drone UDP receiver
it binds to a UDP port and prints incoming messages with timestamp
Sends ACK back to sender
"""
import argparse
import socket
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=5001, help="UDP port to listen on")
    parser.add_argument("--ack", action="store_true", help="Send simple ACK back to sender")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    print(f"[udp_listener] Listening on {args.host}:{args.port}")
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(f"[{ts}] From {addr}: {data.decode('utf-8', errors='replace')}")
            if args.ack:
                sock.sendto(b'{"ack":true}', addr)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print("[udp_listener] Stopped.")

if __name__ == "__main__":
    main()


