NUTRITION LOGGER
================
A personal nutrition tracking system that logs everything you eat
to a local database with full micro and macronutrient profiles.
Draws from two food databases: USDA (US) and McCance & Widdowson CoFID (UK).



━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEFORE YOU START — API KEYS AND COSTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You need two API keys. These are like passwords that give the
software access to the AI and food database services it uses.

1. ANTHROPIC API KEY (small cost)
   This powers the AI that reads your food log and understands
   natural language. It is NOT free, but costs very little:
   - Typical cost: £0.01–0.05 per day of logging
   - You pay only for what you use (no subscription)
   - £5 of credit lasts most people several months

   To get one:
   → Go to console.anthropic.com and create an account
   → Go to Settings → API Keys → Create Key
   → Go to Billing → Add a payment method
   → Add £5–10 of credit to get started
   → Copy your key (starts with sk-ant-...)

2. USDA FOOD DATABASE KEY (completely free)
   This gives access to the US Department of Agriculture's
   nutritional database — no cost, no card required.

   To get one:
   → Go to fdc.nal.usda.gov/api-key-signup.html
   → Enter your email address
   → Your key arrives by email within a few minutes

Keep both keys safe and do not share them with anyone.
The setup script will ask you to paste them in.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT SOFTWARE DO I NEED?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You need Python 3.11 installed. The setup script installs
everything else automatically.

IMPORTANT: Install Python from python.org, NOT from the Mac
App Store or via Homebrew. The official installer works reliably.

→ Go to python.org/downloads
→ Download Python 3.11.x (look for it in the list)
→ Run the installer, click through all the defaults

HOW DO YOU RUN IT?
------------------
You run it from a terminal (a text-based window where you
type commands). Every operating system has one built in:

  Mac:     Terminal (press Cmd+Space, type Terminal)
  Windows: Command Prompt or PowerShell
           (press Windows key, type cmd or powershell)
  Linux:   Terminal or Konsole

You can also run it from inside a code editor if you prefer:

  VS Code  — free, popular, works on Mac/Windows/Linux
             download at code.visualstudio.com
  PyCharm  — free community edition, good for beginners
             download at jetbrains.com/pycharm
  Cursor   — AI-powered code editor, similar to VS Code

IS IT COMPATIBLE ACROSS DIFFERENT COMPUTERS?
--------------------------------------------
Yes. The software runs identically on:
  ✓ Mac (macOS 10.15 or newer)
  ✓ Windows (Windows 10 or 11)
  ✓ Linux

NOTE FOR WINDOWS USERS:
On Windows, use "py" instead of "python3" in all commands:
  py setup.py
  py log_today.py
  py query.py


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIRST TIME SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Install Python 3.11 from python.org (see above)

2. Put ALL the files in a folder, e.g.:
      Mac/Linux:  ~/nutrition-logger
      Windows:    C:\Users\YourName\nutrition-logger

   The package includes these files — keep them all together:
      nutrition_logger.py
      log_today.py
      query.py
      setup.py
      cofid.db         ← UK food database (must be included)
      README.txt

3. Open your terminal and navigate to that folder:
      Mac/Linux:  cd ~/nutrition-logger
      Windows:    cd C:\Users\YourName\nutrition-logger

4. Run the setup script:
      Mac/Linux:  python3 setup.py
      Windows:    py setup.py

   This installs all required packages and asks for your
   two API keys. Takes about 2 minutes.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DAILY USE — LOGGING YOUR DIET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Open your terminal, navigate to your folder, then run:

    Mac/Linux:  python3 log_today.py
    Windows:    py log_today.py

You will see a menu with six options:
  1 — Type your food log interactively (meal by meal)
  2 — Load from a typed/digital PDF
  3 — Load from a handwritten PDF (AI reads the handwriting)
  4 — Load from a photo of your food diary (JPG or PNG)
  5 — Edit the text directly in the script
  6 — Retry last transcription (if option 3 or 4 failed mid-way)

You can run it multiple times per day to add meals as you go.
Each run adds to the database without overwriting previous entries.

ENTERING INGREDIENTS (option 1):
Type each item on its own line with quantity, e.g.:
  chicken breast grilled 100g
  broccoli raw 120g
  rice white cooked 150g
Type END on its own line when finished.

You will be asked which meal it is (breakfast, lunch, dinner,
snack, or supplement) before entering items.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DAILY USE — QUERYING YOUR DATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Mac/Linux:  python3 query.py
    Windows:    py query.py

You will see a menu with two options:
  1 — Analyse a meal (type ingredients, get instant breakdown)
  2 — Query your logged data in plain English

For option 2, choose a time window then ask anything, e.g.:
  What was my average protein intake this week?
  Which day had the highest omega-3 intake?
  How does my magnesium compare to the 300mg RNI?
  Which meal category contributes most of my saturated fat?
  Am I consistently hitting my vitamin D target?
  What were my top 3 sources of iron this week?

Type EXIT to quit.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILES IN THIS PACKAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Share all of these (do not leave any out):
    nutrition_logger.py   — main engine (do not edit)
    log_today.py          — run this to log your diet
    query.py              — run this to query your data
    setup.py              — run once on first install
    cofid.db              — UK food composition database
    README.txt            — this file

These are created automatically and should NOT be shared:
    config.py             — your private API keys
    nutrition_log.db      — your personal nutrition data


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DATA AND PRIVACY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All your nutrition data is stored locally on your own computer
in the nutrition_log.db file. Nothing is uploaded to any server.

Your food log text is sent to Anthropic's API for parsing
(the same AI that powers Claude). Anthropic's data handling
policy applies: anthropic.com/privacy

This software is not a medical device and does not constitute
nutritional or medical advice.
