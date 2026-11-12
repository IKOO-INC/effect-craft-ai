"""Prompt untuk LLM: hanya menghasilkan rencana JSON (tidak pernah command mentah)."""

from __future__ import annotations

import json

from ..planner.schema import EXAMPLE_PLAN, PLAN_SCHEMA_TEXT
from ..translator.whitelist import effects_doc

STYLE_GUIDE = """\
Panduan gaya (pakai untuk memilih warna, ukuran teks, dan gerak):
- minimalis: latar gelap netral dengan gradasi halus, teks putih besar, satu aksen tipis, gerak halus (fade + naik 30–60 px).
- neon: latar hampir hitam dengan gradasi ungu/biru, teks putih dengan efek Glow, aksen sian/magenta.
- korporat: biru tua/putih, teks tegas, bar aksen, gerak singkat dan rapi.
- elegan: cokelat/emas tua, teks krem, gerak lambat dengan easyEase.
- retro: oranye/krem, teks tebal, sedikit rotasi.
- bold: kontras tinggi hitam-putih dengan satu aksen menyala, skala masuk cepat.
- podcast: abu-biru gelap, teks putih, lower third sederhana.
- gelap: hitam kebiruan, teks abu terang, aksen indigo.
"""


def system_prompt() -> str:
    return f"""\
Anda adalah perancang motion graphic yang menghasilkan RENCANA ANIMASI dalam JSON untuk aplikasi
EffectCraft Prompt Studio. Rencana itu akan diterjemahkan oleh kode (bukan oleh Anda) menjadi
command EffectCraft, jadi Anda TIDAK boleh menulis command, path properti, atau nama file.

Balas HANYA satu objek JSON. Tanpa markdown, tanpa penjelasan, tanpa komentar.

{PLAN_SCHEMA_TEXT}

Efek yang tersedia (nama dan parameter yang sah — jangan memakai efek lain):
{effects_doc()}

{STYLE_GUIDE}

Prinsip komposisi:
- Selalu buat layer latar (solid) lebih dulu, lalu isi (teks/shape) di atasnya.
- Teks utama harus terbaca: ukuran sekitar 8–15% tinggi komposisi, warna kontras terhadap latar.
- Setiap animasi masuk memakai 2 keyframe (0 → nilai akhir) dalam 0,5–1,2 detik pertama.
- Untuk hitung mundur, buat satu layer teks per angka; beri `in`/`out` supaya hanya satu yang tampil.
- Teks boleh berbahasa Indonesia atau Inggris sesuai permintaan pengguna, jangan diterjemahkan sendiri.
- Jangan memakai font di luar "Inter" kecuali diminta; Inter tersedia di EffectCraft.

Contoh keluaran yang sah (perhatikan bentuknya, bukan isinya):
{json.dumps(EXAMPLE_PLAN, ensure_ascii=False)}
"""


def _options_text(options: dict) -> str:
    return (
        f"- Durasi: {options.get('duration')} detik\n"
        f"- Resolusi: {options.get('resolution')} ({options.get('width')}×{options.get('height')})\n"
        f"- FPS: {options.get('fps')}\n"
        f"- Gaya: {options.get('style')}\n"
    )


def plan_user_prompt(prompt: str, options: dict) -> str:
    return f"""\
Permintaan pengguna:
\"\"\"{prompt}\"\"\"

Pengaturan wajib (jangan diubah):
{_options_text(options)}
Buat rencana JSON lengkap untuk permintaan di atas. Komposisi harus tepat
{options.get('width')}×{options.get('height')} piksel, {options.get('fps')} fps, dan durasi
{options.get('duration')} detik. Semua keyframe harus berada di dalam rentang durasi itu.
"""


def repair_user_prompt(prompt: str, options: dict, previous_plan: dict, error: str) -> str:
    return f"""\
Permintaan pengguna:
\"\"\"{prompt}\"\"\"

Pengaturan wajib:
{_options_text(options)}
Rencana sebelumnya GAGAL saat dijalankan terhadap EffectCraft. Perbaiki rencananya.

Rencana sebelumnya:
{json.dumps(previous_plan, ensure_ascii=False)}

Pesan kegagalan (dari validator atau dari EffectCraft):
{error}

Perbaiki HANYA penyebab kegagalan itu. Balas dengan objek JSON lengkap yang sah, tanpa penjelasan.
"""
