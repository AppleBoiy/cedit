"""
Dedicated Game Editor Suite for Hades and Hades II.

Full parity with hadessaveeditor.app:
- General (God Mode level, God Mode, Hell Mode, Runs, Grasp, Location)
- Resources (Common, Ores, Boss Rewards, Alchemy)
- Garden (Harvested, Grown Crops, Seeds)
- Gifts & Indulgences (Nectar, Bath Salts, Twin Lures, Ambrosia, Witch's Delight, Obol Points, etc.)
- Fish (All 27 regional fish species)
- Current Run (Health, Max Health, Magick, Max Magick, Death Defiances, Fates Rerolls)
- Arcana Cards (All 25 Cards with Rank & Unlock states)
- Keepsakes (All 33 Keepsakes with Rank & Chamber counts)
- Unlocks (Testaments, Boss Difficulty Upgrades, and Hidden Aspects)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog, QMessageBox,
    QTabWidget, QSpinBox, QGroupBox, QScrollArea, QListWidget,
    QListWidgetItem, QCheckBox, QFrame, QSplitter
)

from lib.base import GAME_WINDOW_SIZE, GAME_WINDOW_MIN, backup_file
from lib import hades_lib
from games import hades2 as hades2_profile
from games import hades as hades_profile

HADES2_SECTIONS = [
    {
        "title": "General",
        "groups": [
            ("Settings", [
                ("EasyModeLevel", "God Mode Level (0-30)", "state_num", 0, 30),
                ("EasyMode", "God Mode Active", "header_bool", 0, 1),
                ("HardMode", "Hell Mode Active", "header_bool", 0, 1),
                ("Runs", "Total Runs Count", "header_int", 0, 99999),
                ("Grasp", "Grasp Capacity", "header_int", 0, 100),
                ("Location", "Active Room / Location", "header_str", 0, 0),
            ])
        ]
    },
    {
        "title": "Resources",
        "groups": [
            ("Common Currencies", [
                ("MetaCurrency", "Bones", "res", 0, 999999),
                ("MemPointsCommon", "Psyche", "res", 0, 99999),
                ("MetaCardPointsCommon", "Ash", "res", 0, 99999),
                ("MetaFabric", "Fate Fabric", "res", 0, 9999),
                ("CardUpgradePoints", "Moon Dust", "res", 0, 9999),
                ("GemPoints", "Gemstones", "res", 0, 99999),
                ("TrashPoints", "Rubbish", "res", 0, 9999),
            ]),
            ("Ores & Minerals", [
                ("OreFSilver", "Silver", "res", 0, 999),
                ("OreGLime", "Limestone", "res", 0, 999),
                ("OreHGlassrock", "Glassrock", "res", 0, 999),
                ("OreIMarble", "Marble", "res", 0, 999),
                ("OreNBronze", "Bronze", "res", 0, 999),
                ("OreOIron", "Iron", "res", 0, 999),
                ("OrePAdamant", "Adamant", "res", 0, 999),
                ("OreQScales", "Serpent Scales", "res", 0, 999),
                ("OreChaosProtoplasm", "Flux", "res", 0, 999),
            ]),
            ("Boss Rewards", [
                ("MixerFBoss", "Cinder (Hecate)", "res", 0, 999),
                ("MixerGBoss", "Pearl (Scylla)", "res", 0, 999),
                ("MixerHBoss", "Tears (Cerberus)", "res", 0, 999),
                ("MixerIBoss", "Zodiac Sand (Chronos)", "res", 0, 999),
                ("MixerNBoss", "Wool (Polyphemus)", "res", 0, 999),
                ("MixerOBoss", "Golden Apple (Eris)", "res", 0, 999),
                ("MixerPBoss", "Feather (Prometheus)", "res", 0, 999),
                ("MixerQBoss", "Void Lens (Typhon)", "res", 0, 999),
            ]),
            ("Alchemy Materials", [
                ("WeaponPointsRare", "Nightmare", "res", 0, 999),
                ("Mixer5Common", "Star Dust", "res", 0, 999),
                ("Mixer6Common", "Darkness", "res", 0, 999),
                ("MixerShadow", "Shadow", "res", 0, 999),
                ("MixerMythic", "Entropy", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Garden",
        "groups": [
            ("Harvested Plants & Flora", [
                ("PlantFMoly", "Moly", "res", 0, 999),
                ("PlantGLotus", "Lotus", "res", 0, 999),
                ("PlantHMyrtle", "Myrtle", "res", 0, 999),
                ("PlantIShaderot", "Shaderot", "res", 0, 999),
                ("PlantNMoss", "Moss", "res", 0, 999),
                ("PlantODriftwood", "Driftwood", "res", 0, 999),
                ("PlantPIris", "Iris", "res", 0, 999),
                ("PlantQFang", "Fangs", "res", 0, 999),
            ]),
            ("Grown Crops", [
                ("PlantFNightshade", "Nightshade", "res", 0, 999),
                ("PlantGCattail", "Cattail", "res", 0, 999),
                ("PlantHWheat", "Wheat", "res", 0, 999),
                ("PlantIPoppy", "Poppy", "res", 0, 999),
                ("PlantNGarlic", "Garlic", "res", 0, 999),
                ("PlantOMandrake", "Mandrake Root", "res", 0, 999),
                ("PlantPOlive", "Olive", "res", 0, 999),
                ("PlantQSnakereed", "Snake-reed", "res", 0, 999),
                ("PlantChaosThalamus", "Thalamus", "res", 0, 999),
            ]),
            ("Garden Seeds", [
                ("PlantChaosThalamusSeed", "Origin Seeds", "res", 0, 999),
                ("PlantFNightshadeSeed", "Nightshade Seeds", "res", 0, 999),
                ("PlantGCattailSeed", "Cattail Seeds", "res", 0, 999),
                ("PlantHWheatSeed", "Wheat Seeds", "res", 0, 999),
                ("PlantIPoppySeed", "Poppy Seeds", "res", 0, 999),
                ("PlantNGarlicSeed", "Garlic Cloves", "res", 0, 999),
                ("PlantOMandrakeSeed", "Mandrake Seeds", "res", 0, 999),
                ("PlantPOliveSeed", "Olive Branch", "res", 0, 999),
                ("PlantQSnakereedSeed", "Plankton", "res", 0, 999),
                ("SeedMystery", "Mystery Seeds", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Gifts & Indulgences",
        "groups": [
            ("Affinity Gifts", [
                ("GiftPoints", "Nectar", "res", 0, 999),
                ("GiftPointsRare", "Bath Salts", "res", 0, 999),
                ("GiftPointsEpic", "Twin Lures", "res", 0, 999),
                ("SuperGiftPoints", "Ambrosia", "res", 0, 999),
                ("FamiliarPoints", "Witch's Delight", "res", 0, 999),
                ("CharonPoints", "Obol Points", "res", 0, 999),
                ("MedeaPoints", "Tears, Vaporized", "res", 0, 999),
                ("IcarusPoints", "Ectoplasmic Draught", "res", 0, 999),
                ("HadesSpearPoints", "Gigaros", "res", 0, 999),
                ("DeathAreaPoints", "House Soot", "res", 0, 999),
                ("HypnosPoints", "Dream Vapors", "res", 0, 999),
                ("DreamPoints", "Shiny Stars", "res", 0, 999),
                ("CosmeticsPoints", "Kudos", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Fish Catches",
        "groups": [
            ("Erebus", [("FishFCommon", "Moper", "res", 0, 99), ("FishFRare", "Figment", "res", 0, 99), ("FishFLegendary", "Soulbelly", "res", 0, 99)]),
            ("Oceanus", [("FishGCommon", "Chiton", "res", 0, 99), ("FishGRare", "Gutterpop", "res", 0, 99), ("FishGLegendary", "Stalkfin", "res", 0, 99)]),
            ("Fields of Mourning", [("FishHCommon", "Soby", "res", 0, 99), ("FishHRare", "Anguish", "res", 0, 99), ("FishHLegendary", "Tearjerker", "res", 0, 99)]),
            ("Tartarus", [("FishICommon", "Jiffy", "res", 0, 99), ("FishIRare", "Goldfish", "res", 0, 99), ("FishILegendary", "Styxeon", "res", 0, 99)]),
            ("City of Ephyra", [("FishNCommon", "Ribeye", "res", 0, 99), ("FishNRare", "Zeel", "res", 0, 99), ("FishNLegendary", "Neckbiter", "res", 0, 99)]),
            ("Rift of Thessaly", [("FishOCommon", "Shrimp", "res", 0, 99), ("FishORare", "Chrab", "res", 0, 99), ("FishOLegendary", "Squid", "res", 0, 99)]),
            ("Mount Olympus", [("FishPCommon", "Pillartop", "res", 0, 99), ("FishPRare", "Chrestle", "res", 0, 99), ("FishPLegendary", "Starsailor", "res", 0, 99)]),
            ("The Summit", [("FishQCommon", "Lamprey", "res", 0, 99), ("FishQRare", "Stormgullet", "res", 0, 99), ("FishQLegendary", "Chimaerid", "res", 0, 99)]),
            ("Chaos", [("FishChaosCommon", "Mati", "res", 0, 99), ("FishChaosRare", "Projelly", "res", 0, 99), ("FishChaosLegendary", "Voidskate", "res", 0, 99)]),
        ]
    },
    {
        "title": "Arcana Cards",
        "groups": [
            ("Altar of Ashes (All 25 Cards: Rank 1-3 & Unlocked Status)", [
                ("ChanneledCast", "I. The Sorceress", "arcana_card", 1, 3),
                ("HealthRegen", "II. The Wayward Son", "arcana_card", 1, 3),
                ("LowManaDamageBonus", "III. The Huntress", "arcana_card", 1, 3),
                ("CastCount", "IV. Eternity", "arcana_card", 1, 3),
                ("SorceryRegenUpgrade", "V. The Moon", "arcana_card", 1, 3),
                ("CastBuff", "VI. The Furies", "arcana_card", 1, 3),
                ("BonusHealth", "VII. Persistence", "arcana_card", 1, 3),
                ("BonusDodge", "VIII. The Messenger", "arcana_card", 1, 3),
                ("ManaOverTime", "IX. The Unseen", "arcana_card", 1, 3),
                ("MagicCrit", "X. Night", "arcana_card", 1, 3),
                ("SprintShield", "XI. The Swift Runner", "arcana_card", 1, 3),
                ("LastStand", "XII. Death", "arcana_card", 1, 3),
                ("MaxHealthPerRoom", "XIII. The Centaur", "arcana_card", 1, 3),
                ("StatusVulnerability", "XIV. Origination", "arcana_card", 1, 3),
                ("ChanneledBlock", "XV. The Lovers", "arcana_card", 1, 3),
                ("TradeOff", "XVI. The Fates", "arcana_card", 1, 3),
                ("StartingGold", "XVII. The Boatman", "arcana_card", 1, 3),
                ("MetaToRunUpgrade", "XVIII. The Artificer", "arcana_card", 1, 3),
                ("RarityBoost", "XIX. Excellence", "arcana_card", 1, 3),
                ("BonusRarity", "XX. The Queen", "arcana_card", 1, 3),
                ("DoorReroll", "XXI. The Enchantress", "arcana_card", 1, 3),
                ("ScreenReroll", "XXII. The Champions", "arcana_card", 1, 3),
                ("LowHealthBonus", "XXIII. Strength", "arcana_card", 1, 3),
                ("EpicRarityBoost", "XXIV. Divinity", "arcana_card", 1, 3),
                ("CardDraw", "XXV. Judgment", "arcana_card", 1, 3),
            ])
        ]
    },
    {
        "title": "Keepsakes",
        "groups": [
            ("Keepsake Chambers / Affinity", [
                ("ManaOverTimeRefundKeepsake", "Silver Wheel (Hecate)", "keepsake", 0, 100),
                ("BossPreDamageKeepsake", "Knuckle Bones (Odysseus)", "keepsake", 0, 100),
                ("ReincarnationKeepsake", "Luckier Tooth (Skelly)", "keepsake", 0, 100),
                ("DoorHealReserveKeepsake", "Ghost Onion (Dora)", "keepsake", 0, 100),
                ("DeathVengeanceKeepsake", "Evil Eye (Nemesis)", "keepsake", 0, 100),
                ("BonusMoneyKeepsake", "Gold Purse (Charon)", "keepsake", 0, 100),
                ("BlockDeathKeepsake", "Engraved Pin (Moros)", "keepsake", 0, 100),
                ("EscalatingKeepsake", "Discordant Bell (Eris)", "keepsake", 0, 100),
                ("TimedBuffKeepsake", "Metallic Droplet (Hermes)", "keepsake", 0, 100),
                ("LowHealthCritKeepsake", "White Antler (Artemis)", "keepsake", 0, 100),
                ("SpellTalentKeepsake", "Moon Beam (Selene)", "keepsake", 0, 100),
                ("ForceZeusBoonKeepsake", "Cloud Bangle (Zeus)", "keepsake", 0, 100),
                ("ForceHeraBoonKeepsake", "Iridescent Fan (Hera)", "keepsake", 0, 100),
                ("ForcePoseidonBoonKeepsake", "Vivid Sea (Poseidon)", "keepsake", 0, 100),
                ("ForceDemeterBoonKeepsake", "Barley Sheaf (Demeter)", "keepsake", 0, 100),
                ("ForceApolloBoonKeepsake", "Harmonic Photon (Apollo)", "keepsake", 0, 100),
                ("ForceAphroditeBoonKeepsake", "Beautiful Mirror (Aphrodite)", "keepsake", 0, 100),
                ("ForceHephaestusBoonKeepsake", "Adamant Shard (Hephaestus)", "keepsake", 0, 100),
                ("ForceHestiaBoonKeepsake", "Everlasting Ember (Hestia)", "keepsake", 0, 100),
                ("ForceAresBoonKeepsake", "Sword Hilt (Ares)", "keepsake", 0, 100),
                ("AthenaEncounterKeepsake", "Gorgon Amulet (Athena)", "keepsake", 0, 100),
                ("SkipEncounterKeepsake", "Fig Leaf (Dionysus)", "keepsake", 0, 100),
                ("ArmorGainKeepsake", "Silken Sash (Arachne)", "keepsake", 0, 100),
                ("FountainRarityKeepsake", "Aromatic Phial (Narcissus)", "keepsake", 0, 100),
                ("UnpickedBoonKeepsake", "Concave Stone (Echo)", "keepsake", 0, 100),
                ("DecayingBoostKeepsake", "Lion Fang (Heracles)", "keepsake", 0, 100),
                ("DamagedDamageBoostKeepsake", "Blackened Fleece (Medea)", "keepsake", 0, 100),
                ("BossMetaUpgradeKeepsake", "Crystal Figurine (Circe)", "keepsake", 0, 100),
                ("TempHammerKeepsake", "Experimental Hammer (Icarus)", "keepsake", 0, 100),
                ("HadesAndPersephoneKeepsake", "Jeweled Pom (Hades & Persephone)", "keepsake", 0, 100),
                ("RarifyKeepsake", "Calling Card (Zagreus)", "keepsake", 0, 100),
                ("GoldifyKeepsake", "Time Piece (Chronos)", "keepsake", 0, 100),
                ("RandomBlessingKeepsake", "Transcendent Embryo (Chaos)", "keepsake", 0, 100),
            ])
        ]
    },
    {
        "title": "Unlocks & Aspects",
        "groups": [
            ("Weapons & Hidden Aspects", [
                ("StaffRaiseDeadAspect", "Aspect of Anubis (Witch's Staff)", "weapon_unlock", 0, 1),
                ("DaggerTripleAspect", "Aspect of the Morrigan (Sister Blades)", "weapon_unlock", 0, 1),
                ("TorchAutofireAspect", "Aspect of Supay (Umbral Flames)", "weapon_unlock", 0, 1),
                ("AxeRallyAspect", "Aspect of Nergal (Moonstone Axe)", "weapon_unlock", 0, 1),
                ("LobGunAspect", "Aspect of Hel (Argent Skull)", "weapon_unlock", 0, 1),
                ("SuitComboAspect", "Aspect of Shiva (Black Coat)", "weapon_unlock", 0, 1),
            ]),
            ("Crossroads Upgrades", [
                ("WorldUpgradeBossDifficultyT2", "Rivals of Depth and Sea (Scylla T2)", "world_upgrade", 0, 1),
                ("WorldUpgradeBossDifficultyT3", "Rivals of Plain and Peak (Cerberus T3)", "world_upgrade", 0, 1),
                ("WorldUpgradeBossDifficultyT4", "Rivals of Old and Rot (Chronos T4)", "world_upgrade", 0, 1),
                ("WorldUpgradeAutoHarvestOnExit", "Greatest Gift of Gaia (Auto Harvest)", "world_upgrade", 0, 1),
            ])
        ]
    },
    {
        "title": "Active Run",
        "groups": [
            ("Current Run Hero Stats", [
                ("Health", "Current Health", "run_hero", 0, 9999),
                ("MaxHealth", "Max Health", "run_hero", 0, 9999),
                ("Mana", "Current Magick", "run_hero", 0, 9999),
                ("MaxMana", "Max Magick", "run_hero", 0, 9999),
                ("MaxLastStands", "Max Death Defiances", "run_hero", 0, 10),
                ("NumRerolls", "Fates (Rerolls)", "run_meta", 0, 99),
            ])
        ]
    }
]



class FixTextureDialog(QDialog):
    """
    Utility to fix the Hades II low-VRAM automatic texture downscaling bug.
    Swaps 1080p and 720p directories in Movies and Packages so the game loads
    high-res assets even on integrated/low VRAM GPUs.
    """
    def __init__(self, parent=None, initial_path=None):
        super().__init__(parent)
        self.setWindowTitle("Fix Texture - Hades II Resolution Fix")
        self.resize(650, 420)
        self.content_dir = hades_lib.resolve_hades2_content_dir(initial_path)
        self._build_ui()
        self._refresh_status()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header Info Banner
        info_group = QGroupBox("Why this fix exists")
        info_layout = QVBoxLayout(info_group)
        info_label = QLabel(
            "When running on devices with lower VRAM, Apple Silicon, or integrated graphics, "
            "Hades II automatically forces 720p textures and video packages to prevent memory pressure, "
            "even if in-game graphics settings are set to High.<br><br>"
            "This fix swaps the <b>720p</b> and <b>1080p</b> directories inside <code>Content/Movies</code> "
            "and <code>Content/Packages</code>, ensuring the game engine loads the full 1080p high-resolution "
            "assets whenever it attempts to load downscaled assets."
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        layout.addWidget(info_group)

        # Path Selection Group
        path_box = QGroupBox("Hades II Content Directory")
        path_layout = QHBoxLayout(path_box)
        self.path_edit = QLineEdit()
        self.path_edit.setText(str(self.content_dir) if self.content_dir else "")
        self.path_edit.textChanged.connect(self._on_path_changed)
        path_layout.addWidget(self.path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        path_layout.addWidget(browse_btn)
        layout.addWidget(path_box)

        # Status & Diagnostics Box
        self.status_box = QGroupBox("Current Asset Status")
        status_layout = QVBoxLayout(self.status_box)

        self.badge_label = QLabel()
        self.badge_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px; border-radius: 4px;")
        status_layout.addWidget(self.badge_label)

        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        status_layout.addWidget(self.details_label)
        layout.addWidget(self.status_box)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.swap_btn = QPushButton()
        self.swap_btn.setStyleSheet("font-weight: bold; padding: 8px 16px;")
        self.swap_btn.clicked.connect(self._toggle_swap)
        btn_layout.addWidget(self.swap_btn, stretch=1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _on_path_changed(self):
        txt = self.path_edit.text().strip()
        self.content_dir = hades_lib.resolve_hades2_content_dir(txt)
        self._refresh_status()

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Hades II Content or Game Folder", str(self.content_dir or ""))
        if d:
            self.path_edit.setText(d)

    def _refresh_status(self):
        if not self.content_dir or not self.content_dir.is_dir():
            self.badge_label.setText("CONTENT DIRECTORY NOT FOUND")
            self.badge_label.setStyleSheet("background-color: #552222; color: #ff9999; padding: 6px; font-weight: bold;")
            self.details_label.setText("Please click Browse... to locate your Hades II installation folder.")
            self.swap_btn.setEnabled(False)
            self.swap_btn.setText("Force High-Res (Unavailable)")
            return

        status = hades_lib.get_hades2_texture_status(self.content_dir)
        if not status.get("valid"):
            self.badge_label.setText("INVALID CONTENT DIRECTORY")
            self.badge_label.setStyleSheet("background-color: #552222; color: #ff9999; padding: 6px; font-weight: bold;")
            self.details_label.setText(f"Error: {status.get("error")}")
            self.swap_btn.setEnabled(False)
            self.swap_btn.setText("Force High-Res (Unavailable)")
            return

        self.swap_btn.setEnabled(True)
        if status.get("is_swapped"):
            self.badge_label.setText("ACTIVE: HIGH-RES 1080p FORCING IS ENABLED")
            self.badge_label.setStyleSheet("background-color: #1e4620; color: #73d13d; border: 1px solid #389e0d; padding: 6px; font-weight: bold;")
            self.details_label.setText(
                "<b>Asset Mapping:</b><br>"
                "• <code>Content/Movies/720p</code> ➔ contains <b>1080p</b> high-res movies<br>"
                "• <code>Content/Packages/720p</code> ➔ contains <b>1080p</b> high-res textures & sprites<br>"
                "<i>When the game requests 720p graphics for low VRAM, it automatically receives 1080p assets.</i>"
            )
            self.swap_btn.setText("Restore Default Textures (Revert to Vanilla 720p/1080p)")
            self.swap_btn.setStyleSheet("background-color: #d46b08; color: white; font-weight: bold; padding: 8px 16px;")
        else:
            self.badge_label.setText("INACTIVE: DEFAULT (VANILLA) MAPPING")
            self.badge_label.setStyleSheet("background-color: #2b303b; color: #d8dee9; border: 1px solid #4c566a; padding: 6px; font-weight: bold;")
            self.details_label.setText(
                "<b>Asset Mapping:</b><br>"
                "• <code>Content/Movies/720p</code> ➔ contains 720p standard movies<br>"
                "• <code>Content/Packages/720p</code> ➔ contains 720p downscaled textures<br>"
                "<i>Low VRAM or integrated graphics will load lower resolution textures.</i>"
            )
            self.swap_btn.setText("Force High-Res Textures (Swap 720p <-> 1080p)")
            self.swap_btn.setStyleSheet("background-color: #2b78e4; color: white; font-weight: bold; padding: 8px 16px;")

    def _toggle_swap(self):
        if not self.content_dir:
            return
        was_swapped = hades_lib.get_hades2_texture_status(self.content_dir).get("is_swapped", False)
        ok, msg = hades_lib.swap_hades2_texture_folders(self.content_dir)
        if ok:
            now_swapped = hades_lib.get_hades2_texture_status(self.content_dir).get("is_swapped", False)
            if now_swapped:
                notice = (
                    "<b>High-Res 1080p Textures are now FORCED!</b><br><br>"
                    "<b>What was changed:</b><br>"
                    "• <code>Movies/720p</code> and <code>Movies/1080p</code> folders have been swapped.<br>"
                    "• <code>Packages/720p</code> and <code>Packages/1080p</code> folders have been swapped.<br><br>"
                    "<b>Effect:</b><br>"
                    "Hades II will now display full 1080p high-resolution textures, sprites, and videos.<br><br>"
                    "<b>Important:</b> Please restart Hades II if it is currently running."
                )
            else:
                notice = (
                    "<b>Default Texture Mapping Restored!</b><br><br>"
                    "<b>What was changed:</b><br>"
                    "• <code>Movies</code> and <code>Packages</code> folders have been restored to vanilla layout.<br><br>"
                    "<b>Important:</b> Please restart Hades II if it is currently running."
                )
            QMessageBox.information(self, "Fix Texture Status", notice)
        else:
            QMessageBox.critical(self, "Fix Texture Error", msg)
        self._refresh_status()


class HadesEditorWindow(QDialog):
    def __init__(self, parent=None, game_key="hades2", initial_path=None):
        super().__init__(parent)
        self.game_key = game_key
        self.profile = hades2_profile.PROFILE if game_key == "hades2" else hades_profile.PROFILE
        self.sections = HADES2_SECTIONS

        self.setWindowTitle(f"{self.profile.display_name} Save Editor Suite")
        self.resize(*GAME_WINDOW_SIZE)
        self.setMinimumSize(*GAME_WINDOW_MIN)

        self.current_path = initial_path
        self.data: Optional[Dict[str, Any]] = None
        self._inputs: Dict[str, Tuple[str, QWidget]] = {}

        self._build_ui()

        if self.current_path and os.path.isfile(self.current_path):
            self._load_file(self.current_path)
        else:
            self._discover_and_load_default()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Top Bar
        top_bar = QHBoxLayout()
        self.file_label = QLabel("Save File: (none)")
        self.file_label.setStyleSheet("font-weight: bold;")
        top_bar.addWidget(self.file_label, stretch=1)

        open_btn = QPushButton("Open...")
        open_btn.clicked.connect(self._browse_save)
        top_bar.addWidget(open_btn)

        self.discover_combo = QComboBox()
        self.discover_combo.addItem("Discovered Saves...")
        self.discover_combo.currentIndexChanged.connect(self._on_discover_selected)
        top_bar.addWidget(self.discover_combo)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._reload_file)
        top_bar.addWidget(reload_btn)

        if self.game_key == "hades2":
            self.fix_tex_btn = QPushButton("Fix Textures...")
            self.fix_tex_btn.setToolTip("Force 1080p high-resolution textures on low VRAM / Apple Silicon devices")
            self.fix_tex_btn.clicked.connect(self._open_fix_textures)
            top_bar.addWidget(self.fix_tex_btn)
            self._update_fix_texture_btn()

        save_btn = QPushButton("Save Changes")
        save_btn.setStyleSheet("background-color: #2b78e4; color: white; font-weight: bold; padding: 6px 14px;")
        save_btn.clicked.connect(self._save_file)
        top_bar.addWidget(save_btn)

        root.addLayout(top_bar)

        # Main Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        for sec in self.sections:
            tab = self._build_section_tab(sec["groups"])
            self.tabs.addTab(tab, sec["title"])

        # Tester Bar
        tester_bar = QHBoxLayout()
        tester_label = QLabel("Tester Quick Presets:")
        tester_label.setStyleSheet("font-weight: bold; color: #777;")
        tester_bar.addWidget(tester_label)

        btn_add10_all = QPushButton("+10 All Materials")
        btn_add10_all.clicked.connect(lambda: self._batch_add_resources(10))
        tester_bar.addWidget(btn_add10_all)

        btn_add100_curr = QPushButton("+1,000 All Currencies")
        btn_add100_curr.clicked.connect(lambda: self._batch_add_currencies(1000))
        tester_bar.addWidget(btn_add100_curr)

        btn_max_arcana = QPushButton("Max All Arcana (Rank 3)")
        btn_max_arcana.clicked.connect(self._batch_max_arcana)
        tester_bar.addWidget(btn_max_arcana)

        btn_unlock_aspects = QPushButton("Unlock All Hidden Aspects")
        btn_unlock_aspects.clicked.connect(self._batch_unlock_aspects)
        tester_bar.addWidget(btn_unlock_aspects)

        tester_bar.addStretch(1)
        root.addLayout(tester_bar)

    def _build_section_tab(self, groups: List[Tuple[str, List[Tuple]]]) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)

        for group_title, items in groups:
            group_box = QGroupBox(group_title)
            grid = QGridLayout(group_box)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(8)

            grid.addWidget(QLabel("<b>Field / Item</b>"), 0, 0)
            grid.addWidget(QLabel("<b>Internal Key</b>"), 0, 1)
            grid.addWidget(QLabel("<b>Value / State</b>"), 0, 2)
            grid.addWidget(QLabel("<b>Quick Adjustments</b>"), 0, 3)

            for row, (field_key, display_name, field_type, min_v, max_v) in enumerate(items, start=1):
                name_lbl = QLabel(display_name)
                name_lbl.setStyleSheet("font-weight: 500;")
                key_lbl = QLabel(f"<code>{field_key}</code>")
                key_lbl.setStyleSheet("color: #777;")

                if field_type == "arcana_card":
                    spin = QSpinBox()
                    spin.setRange(1, 3)
                    spin.setValue(1)
                    spin.setFixedWidth(70)

                    chk = QCheckBox("Unlocked")
                    self._inputs[field_key] = ("arcana_card", (spin, chk))

                    ctrl_box = QHBoxLayout()
                    ctrl_box.addWidget(QLabel("Rank:"))
                    ctrl_box.addWidget(spin)
                    ctrl_box.addWidget(chk)
                    ctrl_box.addStretch(1)
                    ctrl_widget = QWidget()
                    ctrl_widget.setLayout(ctrl_box)

                    grid.addWidget(name_lbl, row, 0)
                    grid.addWidget(key_lbl, row, 1)
                    grid.addWidget(ctrl_widget, row, 2)
                    grid.addWidget(QLabel(""), row, 3)

                elif field_type in ("res", "keepsake", "state_num", "header_int", "run_hero", "run_meta"):
                    spin = QSpinBox()
                    spin.setRange(min_v, max_v)
                    spin.setValue(0)
                    spin.setFixedWidth(110)
                    self._inputs[field_key] = (field_type, spin)

                    btn_box = QHBoxLayout()
                    btn_box.setSpacing(4)
                    deltas = [-10, -1, 1, 10, 100] if max_v > 10 else [-1, 1]
                    for d in deltas:
                        btn = QPushButton(f"+{d}" if d > 0 else str(d))
                        btn.setFixedWidth(40)
                        btn.clicked.connect(lambda _, s=spin, delta=d: s.setValue(max(0, s.value() + delta)))
                        btn_box.addWidget(btn)

                    btn_widget = QWidget()
                    btn_widget.setLayout(btn_box)

                    grid.addWidget(name_lbl, row, 0)
                    grid.addWidget(key_lbl, row, 1)
                    grid.addWidget(spin, row, 2)
                    grid.addWidget(btn_widget, row, 3)

                elif field_type in ("header_bool", "weapon_unlock", "world_upgrade"):
                    chk = QCheckBox("Active / Unlocked")
                    self._inputs[field_key] = (field_type, chk)
                    grid.addWidget(name_lbl, row, 0)
                    grid.addWidget(key_lbl, row, 1)
                    grid.addWidget(chk, row, 2)
                    grid.addWidget(QLabel(""), row, 3)

                elif field_type == "header_str":
                    line = QLineEdit()
                    self._inputs[field_key] = (field_type, line)
                    grid.addWidget(name_lbl, row, 0)
                    grid.addWidget(key_lbl, row, 1)
                    grid.addWidget(line, row, 2)
                    grid.addWidget(QLabel(""), row, 3)

            layout.addWidget(group_box)

        layout.addStretch(1)
        scroll.setWidget(widget)
        return scroll

    def _discover_and_load_default(self):
        found = self.profile.discover_saves()
        self.discover_combo.blockSignals(True)
        self.discover_combo.clear()
        self.discover_combo.addItem("Discovered Saves...")
        for s in found:
            self.discover_combo.addItem(os.path.basename(s), s)
        self.discover_combo.blockSignals(False)

        if found:
            self._load_file(found[0])

    def _on_discover_selected(self, index: int):
        if index > 0:
            path = self.discover_combo.itemData(index)
            if path and os.path.isfile(path):
                self._load_file(path)

    def _open_fix_textures(self):
        dialog = FixTextureDialog(self)
        dialog.exec()
        self._update_fix_texture_btn()

    def _update_fix_texture_btn(self):
        if hasattr(self, "fix_tex_btn") and self.game_key == "hades2":
            content_dir = hades_lib.resolve_hades2_content_dir()
            if content_dir:
                status = hades_lib.get_hades2_texture_status(content_dir)
                if status.get("is_swapped"):
                    self.fix_tex_btn.setText("Fix Textures [HD: ON]")
                    self.fix_tex_btn.setStyleSheet("background-color: #1e4620; color: #73d13d; font-weight: bold;")
                else:
                    self.fix_tex_btn.setText("Fix Textures [HD: OFF]")
                    self.fix_tex_btn.setStyleSheet("")

    def _browse_save(self):
        start_dir = self.profile.find_default_save_dir() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open Hades Save File", start_dir, "Hades Saves (*.sav);;All Files (*.*)")
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        try:
            with open(path, "rb") as f:
                raw = f.read()
            self.data = self.profile.loads(raw)
            self.current_path = path
            self.file_label.setText(f"Save File: {path}")
            self._populate_ui()
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Save", f"Failed to load {path}: {e}")

    def _populate_ui(self):
        if not self.data:
            return

        header = self.data.get("Header", {})
        luabin = self.data.get("_luabin", [{}])
        root = luabin[0] if luabin else {}
        game_state = root.get("GameState", {})
        current_run = root.get("CurrentRun", {})
        hero = current_run.get("Hero", {})
        resources = game_state.get("Resources", {})
        arcana_state = game_state.get("MetaUpgradeState", {})
        keepsake_chambers = game_state.get("KeepsakeChambers", {})
        weapons_unlocked = game_state.get("WeaponsUnlocked", {})
        world_upgrades = game_state.get("WorldUpgradesAdded", {})

        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "res":
                widget.setValue(int(resources.get(field_key, 0)))
            elif f_type == "arcana_card":
                spin, chk = widget
                card = arcana_state.get(field_key, {})
                if isinstance(card, dict):
                    level = int(card.get("Level", 1))
                    unlocked = bool(card.get("Unlocked", False))
                else:
                    level = 1
                    unlocked = bool(card)
                spin.setValue(max(1, min(3, level)))
                chk.setChecked(unlocked)
            elif f_type == "keepsake":
                widget.setValue(int(keepsake_chambers.get(field_key, 0)))
            elif f_type == "weapon_unlock":
                widget.setChecked(bool(weapons_unlocked.get(field_key, False)))
            elif f_type == "world_upgrade":
                widget.setChecked(bool(world_upgrades.get(field_key, False)))
            elif f_type == "state_num":
                widget.setValue(int(game_state.get(field_key, 0)))
            elif f_type == "run_hero":
                widget.setValue(int(hero.get(field_key, 0)))
            elif f_type == "run_meta":
                widget.setValue(int(current_run.get(field_key, 0)))
            elif f_type == "header_int":
                widget.setValue(int(header.get(field_key, 0)))
            elif f_type == "header_bool":
                widget.setChecked(bool(header.get(field_key, False)))
            elif f_type == "header_str":
                widget.setText(str(header.get(field_key, "")))

    def _collect_ui_to_data(self):
        if not self.data:
            return

        header = self.data.setdefault("Header", {})
        luabin = self.data.setdefault("_luabin", [{}])
        root = luabin[0] if luabin else {}
        game_state = root.setdefault("GameState", {})
        current_run = root.setdefault("CurrentRun", {})
        hero = current_run.setdefault("Hero", {})
        resources = game_state.setdefault("Resources", {})
        arcana_state = game_state.setdefault("MetaUpgradeState", {})
        keepsake_chambers = game_state.setdefault("KeepsakeChambers", {})
        weapons_unlocked = game_state.setdefault("WeaponsUnlocked", {})
        world_upgrades = game_state.setdefault("WorldUpgradesAdded", {})

        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "res":
                resources[field_key] = float(widget.value())
            elif f_type == "arcana_card":
                spin, chk = widget
                card = arcana_state.setdefault(field_key, {})
                if not isinstance(card, dict):
                    card = {}
                    arcana_state[field_key] = card
                card["Level"] = float(spin.value())
                card["Unlocked"] = chk.isChecked()
            elif f_type == "keepsake":
                val = widget.value()
                keepsake_chambers[field_key] = float(val)
            elif f_type == "weapon_unlock":
                weapons_unlocked[field_key] = widget.isChecked()
            elif f_type == "world_upgrade":
                world_upgrades[field_key] = widget.isChecked()
            elif f_type == "state_num":
                game_state[field_key] = float(widget.value())
            elif f_type == "run_hero":
                hero[field_key] = float(widget.value())
            elif f_type == "run_meta":
                current_run[field_key] = float(widget.value())
            elif f_type == "header_int":
                header[field_key] = widget.value()
            elif f_type == "header_bool":
                header[field_key] = widget.isChecked()
            elif f_type == "header_str":
                header[field_key] = widget.text().strip()

        # Keep top-level Resources dictionary synchronized
        self.data["Resources"] = resources

    def _save_file(self):
        if not self.current_path or not self.data:
            QMessageBox.warning(self, "No Save Open", "Please open a save file first.")
            return

        try:
            self._collect_ui_to_data()
            backup = backup_file(self.current_path)
            raw_out = self.profile.dumps(self.data)
            with open(self.current_path, "wb") as f:
                f.write(raw_out)
            msg = f"Successfully saved changes to {os.path.basename(self.current_path)}!"
            if backup:
                msg += f" (Backup: {os.path.basename(backup)})"
            QMessageBox.information(self, "Saved", msg)
        except Exception as e:
            QMessageBox.critical(self, "Error Saving File", f"Failed to save file: {e}")

    def _reload_file(self):
        if self.current_path:
            self._load_file(self.current_path)

    def _batch_add_resources(self, amount: int):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "res":
                widget.setValue(widget.value() + amount)

    def _batch_add_currencies(self, amount: int):
        for field_key in ["MetaCurrency", "MemPointsCommon", "MetaCardPointsCommon", "MetaFabric", "CardUpgradePoints"]:
            if field_key in self._inputs:
                _, widget = self._inputs[field_key]
                widget.setValue(widget.value() + amount)

    def _batch_max_arcana(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "arcana_card":
                spin, chk = widget
                spin.setValue(3)
                chk.setChecked(True)

    def _batch_unlock_aspects(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type in ("weapon_unlock", "world_upgrade"):
                widget.setChecked(True)


def launch_hades(parent=None):
    win = HadesEditorWindow(parent, game_key="hades")
    win.show()


def launch_hades2(parent=None):
    win = HadesEditorWindow(parent, game_key="hades2")
    win.show()
