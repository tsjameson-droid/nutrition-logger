"""
setup.py
=========
Run this once when you first set up the nutrition logger.
It installs all required packages and creates your config file.

Run: python3 setup.py
"""

import subprocess, sys, os

print("\n╔══════════════════════════════════════╗")
print("║     Nutrition Logger — Setup         ║")
print("╚══════════════════════════════════════╝\n")

# ── Install packages ──────────────────────────────────────────────────────────

packages = ["anthropic", "requests", "pypdf", "pymupdf"]

print("Installing required packages...\n")
for pkg in packages:
    print(f"  Installing {pkg}...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
        stderr=subprocess.DEVNULL
    )
print("\n✓ All packages installed\n")

# ── Collect API keys ──────────────────────────────────────────────────────────

print("You need two API keys:")
print()
print("  1. Anthropic API key")
print("     → Sign up at console.anthropic.com")
print("     → Go to Settings → API Keys → Create Key")
print("     → Add a payment method under Billing (pay-as-you-go, ~£0.01 per day of logging)")
print()
print("  2. USDA Food Database key (free, instant)")
print("     → Go to fdc.nal.usda.gov/api-key-signup.html")
print("     → Enter your email — key arrives immediately")
print()

anthropic_key = input("Paste your Anthropic API key: ").strip()
usda_key      = input("Paste your USDA API key: ").strip()

# ── Write config.py ───────────────────────────────────────────────────────────

with open("config.py", "w") as f:
    f.write(f'ANTHROPIC_KEY = "{anthropic_key}"\n')
    f.write(f'USDA_KEY = "{usda_key}"\n')

print("\n✓ config.py created\n")

# ── Quick validation ──────────────────────────────────────────────────────────

print("Running a quick check...\n")

try:
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key)
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}]
    )
    print("  ✓ Anthropic API key working")
except Exception as e:
    print(f"  ✗ Anthropic API key issue: {e}")
    print("    Check your key and billing at console.anthropic.com")

try:
    import requests
    r = requests.get(
        "https://api.nal.usda.gov/fdc/v1/foods/search",
        params={"query": "oats", "api_key": usda_key, "pageSize": 1},
        timeout=10
    )
    if r.status_code == 200:
        print("  ✓ USDA API key working")
    else:
        print(f"  ✗ USDA API key issue: status {r.status_code}")
except Exception as e:
    print(f"  ✗ USDA API error: {e}")

print("""
╔══════════════════════════════════════╗
║           Setup complete             ║
╠══════════════════════════════════════╣
║  To log your diet each day, run:     ║
║                                      ║
║    python3 log_today.py              ║
║                                      ║
╚══════════════════════════════════════╝
""")
