# How to run Formula Uno

Everything runs through **one script: `run.py`**. Open a terminal (PowerShell is
fine) and use the commands below. You do **not** need to be in any particular
folder — `run.py` moves itself to the project root automatically.

If `python` isn't recognised, try `py` instead (e.g. `py run.py list`).

---

## 1. See what's available

```
python run.py list
```

Shows the circuits you can use and example commands.

---

## 2. Train the models  *(do this once before predict / api)*

Train every circuit:

```
python run.py train-all
```

…or just one:

```
python run.py train bahrain
```

This downloads the data (first time only — it's cached afterwards), trains the
**race** and **qualifying** models, saves them to `data/models/`, and prints the
accuracy for each year. The **2025** row is the out-of-sample test (a season the
model never trained on).

---

## 3. See a prediction in the terminal  ← the quick "check it myself"

```
python run.py predict bahrain 2025
```

Prints the **predicted finishing order** next to the **actual** result, the error
per driver, and the summary metrics. Try others:

```
python run.py predict spa 2024
python run.py predict austria 2025
```

(Year is optional; it defaults to 2025.)

---

## 4. Compare models — the benchmark

```
python run.py benchmark
python run.py benchmark austria
```

Trains several models (linear, random forest, neural net, XGBoost, LightGBM) on
the same data and prints their cross-validated error side by side.

---

## 5. Run the web API

```
python run.py api
```

Then open **http://127.0.0.1:8000/docs** in your browser and click **“Try it
out”** on `/predict/race`. Press **Ctrl+C** in the terminal to stop the server.

---

## Suggested order the first time

```
python run.py list            # 1. orient yourself
python run.py train-all       # 2. build the models (~5 min, one time)
python run.py predict bahrain 2025   # 3. see a result instantly
python run.py benchmark       # 4. compare models
python run.py api             # 5. explore in the browser
```

## Troubleshooting

- **Lots of red/log text before the results?** That's normal FastF1 chatter —
  the results print at the end. It's now quietened, so there should be little.
- **`predict` or `api` says no model found** → run `python run.py train-all` first.
- **First run of a circuit is slow** → it's downloading data; later runs are instant.
- **`python` not found** → use `py run.py ...`, or check Python is installed.
