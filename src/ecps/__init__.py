"""EffectCraft Prompt Studio — prompt → motion graphic → MP4, mengendalikan EffectCraft.

Paket ini dipisah menjadi beberapa lapisan yang tidak saling bergantung secara melingkar:

    planner   : skema rencana JSON + validasi (tidak menyentuh EffectCraft)
    translator: rencana JSON → urutan command EffectCraft (whitelist)
    runner    : eksekusi command (local CLI / docker / control channel / simulator)
    llm       : klien provider OpenAI-compatible & Anthropic
    storage   : riwayat proyek di Documents/EffectCraftPromptStudio
    ui        : CustomTkinter (tidak diimpor oleh modul lain)
"""

__version__ = "1.0.0"
APP_NAME = "EffectCraft Prompt Studio"
