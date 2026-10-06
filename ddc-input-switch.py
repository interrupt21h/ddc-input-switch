#!/usr/bin/env python3
"""DDC input switcher: standard-library GUI and CLI around ddcutil."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'ddc-input-switch/config.json'
INPUTS = ['0x0f — DisplayPort 1', '0x10 — DisplayPort 2', '0x11 — HDMI 1', '0x12 — HDMI 2', '0x03 — DVI 1', '0x04 — DVI 2', '0x01 — VGA 1']

def value(text):
    token = str(text).split()[0]
    n = int(token[1:], 16) if token.lower().startswith('x') else int(token, 16) if token.lower().startswith('0x') else int(token)
    if not 1 <= n <= 255:
        raise ValueError('Input value must be 1–255 (decimal or 0x hex).')
    return n

def run(*args):
    if not shutil.which('ddcutil'):
        raise RuntimeError('Install ddcutil first; see README.md.')
    try:
        p = subprocess.run(['ddcutil', *map(str, args)], capture_output=True, text=True,
                           timeout=45, env={**os.environ, 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired as e:
        raise RuntimeError('ddcutil timed out after 45 seconds.') from e
    if p.returncode:
        raise RuntimeError((p.stderr + '\n' + p.stdout).strip() or f'ddcutil exited {p.returncode}')
    return p.stdout

def parse_detect(text):
    result = []
    for block in re.split(r'(?m)(?=^Display\s+\d+)', text):
        number = re.match(r'Display\s+(\d+)', block)
        bus = re.search(r'I2C bus:\s*/dev/i2c-(\d+)', block)
        if not number or not bus:
            continue
        def field(name):
            m = re.search(r'^\s*' + re.escape(name) + r':\s*(.*?)\s*$', block, re.M)
            return m.group(1) if m else ''
        result.append({'bus': int(bus.group(1)), 'model': field('Model'),
                       'mfg': field('Mfg id').split()[0] if field('Mfg id') else '',
                       'serial': field('Serial number')})
    return result

def selector(c):
    # A unique EDID ASCII serial survives bus renumbering. Otherwise use explicit bus.
    if c.get('serial') and c.get('model') and c.get('mfg'):
        return ['--mfg', c['mfg'], '--model', c['model'], '--sn', c['serial']]
    return ['--bus', str(int(c['bus']))]

def current(c):
    out = run('getvcp', '60', '--terse', *selector(c))
    m = re.search(r'^VCP 60 SNC (?:0x|x)?([0-9a-fA-F]+)\s*$', out, re.M)
    if not m:
        raise RuntimeError('Cannot read input source:\n' + out.strip())
    return int(m.group(1), 16)

def switch(c, action):
    a, b = value(c['a']), value(c['b'])
    if a == b:
        raise ValueError('Inputs A and B must differ.')
    if action == 'toggle':
        old = current(c)
        if old not in (a, b):
            raise RuntimeError(f'Current input 0x{old:02x} is neither A nor B. Choose A or B explicitly.')
        target = b if old == a else a
    else:
        target = a if action == 'a' else b
    run('setvcp', '60', f'0x{target:02x}', '--noverify', *selector(c))
    return f'Switch request sent: input 0x{target:02x}. Monitor execution is not verified.'

def save(c):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(c, indent=2) + '\n')
    tmp.replace(CONFIG)

def load():
    if not CONFIG.exists():
        return {'bus': 1, 'a': '0x0f', 'b': '0x11'}
    return json.loads(CONFIG.read_text())

def gui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    c = load()
    root = tk.Tk()
    root.title('Monitor Input Switch')
    root.geometry('640x540')
    root.minsize(540, 440)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Monitor Input Switch', font=('', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Choose a monitor and configure two input sources.').pack(anchor='w', pady=(4, 14))
    monitor = tk.StringVar(value=f"Configured: {c.get('model', 'monitor')} · I²C bus {c['bus']}")
    combo = ttk.Combobox(frame, textvariable=monitor, state='readonly')
    combo.pack(fill='x')
    devices = {}
    buttons = []
    events = queue.Queue()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    status = tk.StringVar(value='Detect monitors to configure; saved configuration is ready to use.')
    def job(fn, done=None):
        for button in buttons:
            button.configure(state='disabled')
        status.set('Working…')
        def worker():
            try:
                events.put((True, fn(), done))
            except Exception as e:
                events.put((False, str(e), None))
        pool.submit(worker)
    def poll():
        try:
            ok, result, done = events.get_nowait()
        except queue.Empty:
            pass
        else:
            for button in buttons:
                button.configure(state='normal')
            if ok:
                if done:
                    done(result)
                else:
                    status.set(str(result))
            else:
                status.set('Operation failed. See details below.')
                log.delete('1.0', 'end')
                log.insert('end', result)
                messagebox.showerror('DDC operation failed', result)
        root.after(100, poll)
    def button(parent, text, command):
        b = ttk.Button(parent, text=text, command=command)
        buttons.append(b)
        return b
    def detected(items):
        devices.clear()
        for d in items:
            label = f"{d['model'] or 'Monitor'} · {d['serial'] or 'no serial'} · I²C bus {d['bus']}"
            devices[label] = d
        combo['values'] = list(devices)
        if devices:
            matching = [k for k, d in devices.items() if d['bus'] == c['bus']]
            monitor.set(matching[0] if matching else next(iter(devices)))
        status.set(f'{len(items)} DDC monitor(s) detected. Select one and save configuration.')
    button(frame, 'Detect monitors', lambda: job(lambda: parse_detect(run('detect')), detected)).pack(anchor='w', pady=8)
    fields = ttk.Frame(frame)
    fields.pack(fill='x', pady=8)
    av, bv = tk.StringVar(value=c['a']), tk.StringVar(value=c['b'])
    for row, (label, var) in enumerate([('Input A', av), ('Input B', bv)]):
        ttk.Label(fields, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
        ttk.Combobox(fields, textvariable=var, values=INPUTS).grid(row=row, column=1, sticky='ew', pady=4)
    fields.columnconfigure(1, weight=1)
    ttk.Label(frame, text='Values are monitor dependent. You can type a custom hex value.').pack(anchor='w')
    def config():
        chosen = devices.get(monitor.get(), {k: c[k] for k in ('bus', 'mfg', 'model', 'serial') if k in c})
        result = {**chosen, 'a': f'0x{value(av.get()):02x}', 'b': f'0x{value(bv.get()):02x}'}
        if result['a'] == result['b']:
            raise ValueError('Inputs A and B must differ.')
        return result
    def execute(action):
        try:
            target = config()
        except Exception as e:
            messagebox.showerror('Configuration error', str(e)); return
        job(lambda: switch(target, action))
    def store():
        try:
            new = config()
            save(new)
            c.clear(); c.update(new)
            status.set('Configuration saved for the GUI, CLI and desktop actions.')
        except Exception as e:
            messagebox.showerror('Configuration error', str(e))
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=16)
    for label, act in [('Input A', 'a'), ('Toggle A ↔ B', 'toggle'), ('Input B', 'b')]:
        button(actions, label, lambda act=act: execute(act)).pack(side='left', expand=True, fill='x', padx=3)
    utilities = ttk.Frame(frame)
    utilities.pack(fill='x')
    button(utilities, 'Save configuration', store).pack(side='left')
    def inspect(kind):
        try:
            target = config()
        except Exception as e:
            messagebox.showerror('Configuration error', str(e)); return
        def show(out):
            log.delete('1.0', 'end'); log.insert('end', out)
            status.set('Monitor information loaded.')
        job(lambda: run('capabilities', *selector(target)) if kind == 'caps' else f'Current input: 0x{current(target):02x}', show)
    button(utilities, 'Read current', lambda: inspect('current')).pack(side='left', padx=6)
    button(utilities, 'Capabilities', lambda: inspect('caps')).pack(side='left')
    ttk.Label(frame, textvariable=status, wraplength=590).pack(fill='x', pady=12)
    log = tk.Text(frame, height=7, wrap='word')
    log.pack(fill='both', expand=True)
    log.insert('end', 'Enable DDC/CI in the monitor menu. Switching away may disable DDC access from this computer; use the other computer or the monitor buttons to switch back.')
    root.after(100, poll)
    def close():
        pool.shutdown(wait=False, cancel_futures=True)
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.mainloop()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', nargs='?', default='gui', choices=['gui', 'a', 'b', 'toggle', 'current', 'detect', 'capabilities'])
    p.add_argument('--bus', type=int, help='Override configured monitor with an I²C bus')
    p.add_argument('--input-a', help='Override input A, e.g. 0x0f')
    p.add_argument('--input-b', help='Override input B, e.g. 0x11')
    args = p.parse_args()
    try:
        if args.action == 'gui':
            gui(); return 0
        if args.action == 'detect':
            print(run('detect')); return 0
        if not CONFIG.exists() and args.bus is None:
            raise RuntimeError('Save configuration in the GUI first, or specify --bus and input values.')
        c = load()
        if args.bus is not None:
            c = {**c, 'bus': args.bus, 'serial': '', 'model': '', 'mfg': ''}
        if args.input_a: c['a'] = args.input_a
        if args.input_b: c['b'] = args.input_b
        if args.action == 'current': print(f'0x{current(c):02x}')
        elif args.action == 'capabilities': print(run('capabilities', *selector(c)))
        else: print(switch(c, args.action))
        return 0
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
