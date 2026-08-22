"""Stage-gate prototype: photos -> character sheet -> N scenes -> face scores + cost + time.

Usage:
  SB_IMAGE_PROVIDER=gemini SB_GEMINI_API_KEY=... SB_FACE_QA=insightface \
  python scripts/prototype.py --photos ./proto/photos --out ./proto/out --scenes 3 --name Алихан --age 5 --gender boy

Folder layout: proto/photos/<child_id>/*.jpg  (1–3 photos per child)
Output: proto/out/<child_id>/sheet.png, scene_1.png..., and proto/out/report.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import time
from pathlib import Path

from storybook.content import STYLES, get_plot
from storybook.domain import CharacterSheet, ChildProfile, Gender, ScenePrompt
from storybook.generation import face_qa, illustration_generator
from storybook.storage import strip_exif_and_resize


async def run_child(folder: Path, out: Path, args, gen, qa, writer) -> None:
    photos = [strip_exif_and_resize(p.read_bytes()) for p in sorted(folder.glob("*")) if p.suffix.lower() in (".jpg", ".jpeg", ".png")][:3]
    if not photos:
        return
    child = ChildProfile(name=args.name, age=args.age, gender=Gender(args.gender), photo_keys=["local"])
    plot = get_plot(args.plot)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sheet_res, desc = await gen.make_character_sheet(photos, child, STYLES["soft3d"], plot.hero_outfit)
    (out / "sheet.png").write_bytes(sheet_res.data)
    (out / "description.txt").write_text(desc, encoding="utf-8")
    sheet_score = await qa.similarity(photos[0], sheet_res.data)
    writer.writerow([folder.name, "sheet", sheet_res.model, f"{sheet_score if sheet_score is not None else ''}", f"{sheet_res.cost_usd:.3f}", f"{time.time() - t0:.1f}"])
    sheet = CharacterSheet(image_key="local", reference_photo_key="local", description=desc, model=sheet_res.model)
    total_cost = sheet_res.cost_usd
    for s in plot.scenes[: args.scenes]:
        t1 = time.time()
        scene = ScenePrompt(n=s["n"], text="", scene=f"{s['setting']}; {s['action']}")
        res = await gen.render_page(sheet_res.data, photos[0], sheet, scene, STYLES["soft3d"], plot.hero_outfit, child)
        (out / f"scene_{s['n']}.png").write_bytes(res.data)
        score = await qa.similarity(photos[0], res.data)
        total_cost += res.cost_usd
        writer.writerow([folder.name, f"scene_{s['n']}", res.model, f"{score if score is not None else ''}", f"{res.cost_usd:.3f}", f"{time.time() - t1:.1f}"])
    print(f"{folder.name}: done in {time.time() - t0:.0f}s, cost ${total_cost:.2f}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenes", type=int, default=3)
    ap.add_argument("--plot", default="dragon")
    ap.add_argument("--name", default="Алихан")
    ap.add_argument("--age", type=int, default=5)
    ap.add_argument("--gender", default="boy")
    args = ap.parse_args()
    gen, qa = illustration_generator(), face_qa()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["child", "item", "model", "face_score", "cost_usd", "seconds"])
        for folder in sorted(p for p in Path(args.photos).iterdir() if p.is_dir()):
            await run_child(folder, out_root / folder.name, args, gen, qa, w)
    print(f"report: {out_root / 'report.csv'}")


if __name__ == "__main__":
    asyncio.run(main())
