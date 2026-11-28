#!/usr/bin/env python3
"""Extract the embedded a12_init_wrapper.c heredoc from build_android12_ramdisk.sh.

The upstream script writes the C source inline:

    cat > /tmp/a12_init_wrapper.c <<'EOF'
    ... C code ...
    EOF

We pull out exactly those lines so the caller can compile the static /init
wrapper independently and repair the ramdisk if needed.

Usage: extract_init_wrapper.py <build_ramdisk.sh> <out.c>
"""
import sys

START_MARK = "cat > /tmp/a12_init_wrapper.c <<"
END_MARK = "EOF"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: extract_init_wrapper.py <build_ramdisk.sh> <out.c>", file=sys.stderr)
        return 2
    src_path, out_path = sys.argv[1], sys.argv[2]

    lines = open(src_path, encoding="utf-8", errors="replace").read().splitlines()

    start = None
    for i, ln in enumerate(lines):
        if START_MARK in ln:
            start = i + 1
            break
    if start is None:
        print(f"[x] start marker not found: {START_MARK}", file=sys.stderr)
        return 1

    end = None
    for j in range(start, len(lines)):
        if lines[j].strip() == END_MARK:
            end = j
            break
    if end is None:
        print("[x] end marker EOF not found", file=sys.stderr)
        return 1

    body = lines[start:end]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(body) + "\n")

    print(f"[ok] extracted {len(body)} lines -> {out_path}")

    # sanity: must look like C with an init-ish entry point
    text = "\n".join(body)
    checks = {
        "has #include": "#include" in text,
        "has main(": "main(" in text,
        "mentions first_stage": "first_stage" in text,
        "mentions execv": "execv" in text,
    }
    for k, v in checks.items():
        print(f"    {k}: {'yes' if v else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
