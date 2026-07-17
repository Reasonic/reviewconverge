#!/usr/bin/env python3
"""Generate the human R/F/U audit checklist (HTML) for the realistic-scale probe corpus.

For each seeded defect: the buggy line in context, the description, the paraphrases (to
check they are distinct), and Real / Findable / Unique / Distinct checkboxes. The
maintainer (non-author) confirms each, then defects are flipped confirmed:true and the
probe corpus is frozen for the campaign.
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reviewconverge.corpus import load_corpus  # noqa: E402

OUT = ROOT / "corpus_probe" / "AUDIT_CHECKLIST.html"

# Client-side export logic. Kept as a plain (non-f) string so its many braces are
# inserted verbatim into the document via a single {SCRIPT} placeholder.
SCRIPT = r"""
<script>
const KEY = 'rc-probe-audit-v1';
const CHECKS = ['real','findable','unique','independent'];
const cards = () => [...document.querySelectorAll('[data-defect]')];
const graycards = () => [...document.querySelectorAll('[data-gray]')];

function collect(){
  const defects = cards().map(card => {
    const checks = {};
    card.querySelectorAll('input[data-check]').forEach(cb => checks[cb.dataset.check] = cb.checked);
    const noteEl = card.querySelector('input[data-note]');
    return {id: card.dataset.defect, checks, note: noteEl ? noteEl.value.trim() : '',
            pass: CHECKS.every(k => checks[k])};
  });
  const grays = graycards().map(card => {
    const cb = card.querySelector('input[data-check]');
    const noteEl = card.querySelector('input[data-note]');
    return {id: card.dataset.gray, excluded: cb ? cb.checked : false,
            note: noteEl ? noteEl.value.trim() : ''};
  });
  return {defects, grays};
}

function save(){ try{ localStorage.setItem(KEY, JSON.stringify(collect())); }catch(e){} }
function restore(){
  let d; try{ d = JSON.parse(localStorage.getItem(KEY)); }catch(e){ return; }
  if(!d) return;
  (d.defects||[]).forEach(r => {
    const card = cards().find(c => c.dataset.defect === r.id); if(!card) return;
    card.querySelectorAll('input[data-check]').forEach(cb => cb.checked = !!(r.checks||{})[cb.dataset.check]);
    const n = card.querySelector('input[data-note]'); if(n && r.note) n.value = r.note;
  });
  (d.grays||[]).forEach(g => {
    const card = graycards().find(c => c.dataset.gray === g.id); if(!card) return;
    const cb = card.querySelector('input[data-check]'); if(cb) cb.checked = !!g.excluded;
    const n = card.querySelector('input[data-note]'); if(n && g.note) n.value = g.note;
  });
}

function paint(){
  const {defects, grays} = collect();
  let done = 0;
  cards().forEach(card => {
    const r = defects.find(x => x.id === card.dataset.defect);
    const any = CHECKS.some(k => r.checks[k]);
    card.classList.toggle('done', r.pass);
    card.classList.toggle('flag', any && !r.pass);
    if(r.pass) done++;
  });
  const gdone = grays.filter(g => g.excluded).length;
  document.getElementById('prog').textContent =
    `${done}/${defects.length} defects confirmed · ${gdone}/${grays.length} gray zones`;
}

function checkAll(v){
  document.querySelectorAll('input[data-check]').forEach(cb => cb.checked = v);
  save(); paint();
}

function doExport(){
  const {defects, grays} = collect();
  const flagged = defects.filter(r => !r.pass);
  const grayFlag = grays.filter(g => !g.excluded);
  const L = [];
  L.push('=== ReviewConverge realistic-scale probe — audit result ===');
  L.push(`defects: ${defects.length} total · ${defects.length - flagged.length} fully confirmed (Real+Findable+Unique+Independent) · ${flagged.length} flagged`);
  L.push(`gray zones: ${grays.length} total · ${grays.length - grayFlag.length} confirmed-excluded · ${grayFlag.length} flagged`);
  L.push('');
  if(flagged.length === 0 && grayFlag.length === 0){
    L.push('STATUS: ALL CONFIRMED — probe audit done');
  } else {
    L.push('STATUS: EXCEPTIONS');
    if(flagged.length){
      L.push('', 'FLAGGED DEFECTS:');
      flagged.forEach(r => {
        const miss = CHECKS.filter(k => !r.checks[k]);
        L.push(`- ${r.id}: unconfirmed [${miss.join(', ')}]${r.note ? ' — ' + r.note : ''}`);
      });
    }
    if(grayFlag.length){
      L.push('', 'GRAY ZONES marked NOT-correctly-excluded (possible real bug?):');
      grayFlag.forEach(g => L.push(`- ${g.id}${g.note ? ' — ' + g.note : ''}`));
    }
  }
  const notes = defects.filter(r => r.pass && r.note);
  if(notes.length){
    L.push('', 'NOTES (on confirmed defects):');
    notes.forEach(r => L.push(`- ${r.id}: ${r.note}`));
  }
  L.push('', '--- machine-readable ---', '```json',
         JSON.stringify({defects, grays}, null, 1), '```');
  const text = L.join('\n');
  const out = document.getElementById('out');
  out.value = text;
  out.scrollIntoView({behavior:'smooth', block:'nearest'});
  if(navigator.clipboard){ navigator.clipboard.writeText(text).then(()=>flash('copied to clipboard ✓'), ()=>{}); }
}

function flash(msg){ document.getElementById('prog').textContent = msg; setTimeout(paint, 1500); }

document.addEventListener('input', e => { if(e.target.matches('input')){ save(); paint(); } });
restore(); paint();
</script>
"""


def esc(s):
    return html.escape(str(s))


def main():
    items = sorted(load_corpus(ROOT / "corpus_probe"), key=lambda it: it.id)
    n_def = sum(len(it.defects) for it in items)
    rows = []
    for it in items:
        lm = it.line_map()
        maxln = max(lm) if lm else 0
        unit = (it.defects[0].location.unit if it.defects
                else it.known_gray_zone[0]["location"]["unit"] if it.known_gray_zone
                else it.id)
        rows.append(f"<h2>{esc(it.id)} — {esc(it.meta.get('title',''))} "
                    f"<span class=meta>({len(it.defects)} defects, {maxln} lines)</span></h2>")
        full = "".join(f"<div class=ln><span class=no>{i}</span>{esc(lm.get(i,''))}</div>"
                       for i in range(1, maxln + 1))
        rows.append(f"<details class=fullsrc><summary>full source — <code>{esc(unit)}</code>"
                    f" ({maxln} lines)</summary><div class=code>{full}</div></details>")
        for d in it.defects:
            loc = d.location
            s = loc.start
            ctx = []
            for i in range(max(1, s - 2), s + 3):
                line = lm.get(i, "")
                cls = " bug" if i == s else ""
                ctx.append(f"<div class='ln{cls}'><span class=no>{i}</span>{esc(line)}</div>")
            paras = "".join(f"<li>{esc(p)}</li>" for p in d.paraphrases)
            rows.append(f"""
<div class=card data-defect="{esc(d.id)}">
  <div class=hdr><b>{esc(d.id)}</b> · {esc(d.category)} · {esc(d.severity.value if hasattr(d.severity,'value') else d.severity)}
     · <code>{esc(loc.unit)}:{s}</code></div>
  <div class=desc>{esc(d.description)}</div>
  <div class=code>{''.join(ctx)}</div>
  <details><summary>paraphrases ({len(d.paraphrases)}) — check mutually distinct</summary><ul>{paras}</ul></details>
  <div class=checks>
    <label><input type=checkbox data-check=real> <b>Real</b> (a genuine bug)</label>
    <label><input type=checkbox data-check=findable> <b>Findable</b> (from the file alone)</label>
    <label><input type=checkbox data-check=unique> <b>Unique</b> (distinct root cause)</label>
    <label><input type=checkbox data-check=independent> <b>Independent</b> (not masked by another defect)</label>
    <label class=note>notes: <input type=text data-note size=40></label>
  </div>
</div>""")
        for z in it.known_gray_zone:
            loc = z["location"]
            gs = loc.get("start") or 1
            gctx = []
            for i in range(max(1, gs - 6), min(maxln, gs + 6) + 1):
                line = lm.get(i, "")
                cls = " zone" if i == gs else ""
                gctx.append(f"<div class='ln{cls}'><span class=no>{i}</span>{esc(line)}</div>")
            rows.append(f"""
<div class='card gray' data-gray="{esc(loc['unit'])}:{esc(loc.get('start'))}">
  <div class=hdr><b>gray zone</b> · <code>{esc(loc['unit'])}:{esc(loc.get('start'))}</code>
     <span class=meta>(line approximate — expand full source above for more)</span></div>
  <div class=desc>{esc(z['note'])}</div>
  <div class=code>{''.join(gctx)}</div>
  <div class=checks><label><input type=checkbox data-check=excluded> <b>Plausible</b> &amp; <b>not a seeded defect</b> (correctly excluded)</label>
    <label class=note>notes: <input type=text data-note size=30></label></div>
</div>""")

    body = "\n".join(rows)
    doc = f"""<!doctype html><meta charset=utf-8>
<title>ReviewConverge — realistic-scale probe R/F/U audit</title>
<style>
 :root{{color-scheme:dark}}
 body{{font:14px/1.5 -apple-system,system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#c9d1d9;background:#0d1117}}
 h1{{margin-bottom:.2rem;color:#e6edf3}} h2{{margin-top:2rem;border-bottom:2px solid #30363d;padding-bottom:.2rem;color:#e6edf3}}
 a{{color:#58a6ff}}
 .meta{{color:#8b949e;font-weight:400;font-size:.85em}}
 .card{{border:1px solid #30363d;border-radius:8px;padding:.8rem 1rem;margin:.8rem 0;background:#161b22}}
 .card.gray{{background:#2b2413;border-color:#6b5a1e}}
 .hdr{{font-size:.9em;color:#adbac7;margin-bottom:.3rem}}
 .desc{{margin:.3rem 0 .5rem}}
 .code{{font:12px/1.45 ui-monospace,Menlo,monospace;background:#010409;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:.5rem;overflow-x:auto}}
 .ln{{white-space:pre}} .ln.bug{{background:#3d1d1d;color:#ffb3b3}} .ln.zone{{background:#3a3413;color:#f0d97a}}
 .no{{display:inline-block;width:2.5em;color:#6e7681;user-select:none}}
 details.fullsrc{{margin:.4rem 0 .8rem}} details.fullsrc>summary{{color:#58a6ff}}
 details.fullsrc .code{{max-height:60vh;overflow:auto;margin-top:.3rem}}
 .checks{{margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.5rem 1.2rem;align-items:center}}
 .checks label{{font-size:.9em}} .checks input[type=text]{{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:.15rem .3rem}}
 details{{margin:.4rem 0;font-size:.9em}} summary{{cursor:pointer;color:#8b949e}}
 code{{background:#010409;color:#c9d1d9;padding:0 3px;border-radius:3px}}
 #bar{{position:sticky;top:0;z-index:10;background:#161b22ee;backdrop-filter:blur(6px);border:1px solid #30363d;border-radius:8px;padding:.6rem .9rem;margin:.6rem 0 1rem;display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}}
 #bar button{{font:inherit;background:#238636;color:#fff;border:0;border-radius:6px;padding:.4rem .8rem;cursor:pointer}}
 #bar button.sec{{background:#21262d;color:#c9d1d9;border:1px solid #30363d}}
 #bar .prog{{color:#8b949e;font-size:.9em;margin-left:auto}}
 .card.done{{border-color:#238636}} .card.done .hdr b{{color:#3fb950}}
 .card.flag{{border-color:#f85149}}
 #exportPanel{{margin:2rem 0 3rem}}
 #exportPanel textarea{{width:100%;height:240px;background:#010409;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:.6rem;font:12px/1.45 ui-monospace,Menlo,monospace;box-sizing:border-box}}
</style>
<h1>Realistic-scale probe — human R/F/U audit</h1>
<p><b>{len(items)} modules · {n_def} seeded defects.</b> For each defect confirm it is
<b>Real</b> (a genuine bug), <b>Findable</b> from the file alone, <b>Unique</b> (distinct root
cause), and <b>Independent</b> (its stated consequence holds regardless of the other defects —
not masked). For each gray zone, confirm it is a plausible-but-unseeded smell that is correctly
excluded. Then tell Claude "probe audit done" (or note any defect to fix); Claude flips
<code>confirmed:true</code>, freezes the probe corpus, and runs the campaign.</p>
<p class=meta>These artifacts are freshly authored (memorization 0.10 vs the main corpus 0.28),
so they are essentially uncontaminated — the point of the probe.</p>
<div id=bar>
  <button onclick="checkAll(true)">✓ Confirm all</button>
  <button class=sec onclick="checkAll(false)">Clear all</button>
  <button onclick="doExport()">⬇ Export result</button>
  <span class=prog id=prog></span>
</div>
{body}
<div id=exportPanel>
  <h2>Export</h2>
  <p class=meta>Click <b>⬇ Export result</b> (top bar) — the block below is filled in and copied to
  your clipboard. Paste it straight back to Claude. Cards you fully confirm turn green; partially
  checked cards turn red. Your progress auto-saves in this browser, so a reload won't lose it.</p>
  <textarea id=out readonly placeholder="(click ⬇ Export result to generate)"></textarea>
</div>
{SCRIPT}
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT} — {len(items)} modules, {n_def} defects")


if __name__ == "__main__":
    main()
