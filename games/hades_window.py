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
            ("Settings & Progress", [
                ("EasyModeLevel", "God Mode Level (0-30)", "state_num", 0, 30),
                ("EasyMode", "God Mode Active", "header_bool", 0, 1),
                ("HardMode", "Hell Mode Active", "header_bool", 0, 1),
                ("Runs", "Total Runs Count", "header_int", 0, 99999),
                ("Grasp", "Grasp Capacity (Altar Points)", "header_int", 0, 100),
                ("Location", "Active Room / Location", "header_str", 0, 0),
            ])
        ]
    },
    {
        "title": "Resources",
        "groups": [
            ("Major Currencies & Points", [
                ("MetaCurrency", "Bones", "res", 0, 99999),
                ("MemPointsCommon", "Psyche", "res", 0, 99999),
                ("MetaCardPointsCommon", "Ash", "res", 0, 99999),
                ("MetaFabric", "Fate Fabric", "res", 0, 9999),
                ("CardUpgradePoints", "Moon Dust", "res", 0, 9999),
                ("CardUpgradePointsAdd", "Star Dust", "res", 0, 9999),
                ("TalentPoints", "Shadow", "res", 0, 9999),
                ("MajorTalentPoints", "Zodiac Sand", "res", 0, 9999),
                ("TrashPoints", "Garbage", "res", 0, 999),
            ]),
            ("Mining Ores & Minerals", [
                ("OreFSilver", "Silver (Erebus)", "res", 0, 999),
                ("OreGLime", "Limestone (Oceanus)", "res", 0, 999),
                ("OreHGlassrock", "Glassrock (Fields)", "res", 0, 999),
                ("OreIMarble", "Marble (Tartarus)", "res", 0, 999),
                ("OreJBronze", "Bronze (Ephyra)", "res", 0, 999),
                ("OreKIron", "Iron (Thessaly)", "res", 0, 999),
                ("OreLAdamant", "Adamant (Olympus)", "res", 0, 999),
                ("OreMScales", "Scales (Summit)", "res", 0, 999),
                ("OreNFlux", "Flux (Surface)", "res", 0, 999),
            ]),
            ("Boss Reagents & Trophies", [
                ("MixerFBoss", "Cinder (Hecate)", "res", 0, 999),
                ("MixerGBoss", "Pearl / Tears (Scylla)", "res", 0, 999),
                ("MixerHBoss", "Wool (Polyphemus)", "res", 0, 999),
                ("MixerIBoss", "Golden Apple (Eris)", "res", 0, 999),
                ("MixerJBoss", "Entropy (Chronos)", "res", 0, 999),
                ("MixerPBase", "Moss", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Aspects & Weapons",
        "groups": [
            ("Descura - Witch's Staff", [
                ("StaffMelinoeAspect", "Aspect of Melinoë (Staff)", "aspect_rank", 1, 5),
                ("StaffCirceAspect", "Aspect of Circe", "aspect_rank", 1, 5),
                ("StaffMomusAspect", "Aspect of Momus", "aspect_rank", 1, 5),
                ("StaffRaiseDeadAspect", "Aspect of Anubis (Hidden)", "aspect_rank", 1, 5),
            ]),
            ("Lim and Oros - Sister Blades", [
                ("DaggerMelinoeAspect", "Aspect of Melinoë (Daggers)", "aspect_rank", 1, 5),
                ("DaggerArtemisAspect", "Aspect of Artemis", "aspect_rank", 1, 5),
                ("DaggerPanAspect", "Aspect of Pan", "aspect_rank", 1, 5),
                ("DaggerTripleAspect", "Aspect of the Morrigan (Hidden)", "aspect_rank", 1, 5),
            ]),
            ("Ygnium - Umbral Flames", [
                ("TorchMelinoeAspect", "Aspect of Melinoë (Torches)", "aspect_rank", 1, 5),
                ("TorchMorosAspect", "Aspect of Moros", "aspect_rank", 1, 5),
                ("TorchEosAspect", "Aspect of Eos", "aspect_rank", 1, 5),
                ("TorchAutofireAspect", "Aspect of Supay (Hidden)", "aspect_rank", 1, 5),
            ]),
            ("Zorephet - Moonstone Axe", [
                ("AxeMelinoeAspect", "Aspect of Melinoë (Axe)", "aspect_rank", 1, 5),
                ("AxeCharonAspect", "Aspect of Charon", "aspect_rank", 1, 5),
                ("AxeThanatosAspect", "Aspect of Thanatos", "aspect_rank", 1, 5),
                ("AxeRallyAspect", "Aspect of Nergal (Hidden)", "aspect_rank", 1, 5),
            ]),
            ("Revaal - Argent Skull", [
                ("LobMelinoeAspect", "Aspect of Melinoë (Skull)", "aspect_rank", 1, 5),
                ("LobMedeaAspect", "Aspect of Medea", "aspect_rank", 1, 5),
                ("LobPersephoneAspect", "Aspect of Persephone", "aspect_rank", 1, 5),
                ("LobGunAspect", "Aspect of Hel (Hidden)", "aspect_rank", 1, 5),
            ]),
            ("Althea - Black Coat", [
                ("SuitMelinoeAspect", "Aspect of Melinoë (Coat)", "aspect_rank", 1, 5),
                ("SuitNyxAspect", "Aspect of Nyx", "aspect_rank", 1, 5),
                ("SuitSeleneAspect", "Aspect of Selene", "aspect_rank", 1, 5),
                ("SuitComboAspect", "Aspect of Shiva (Hidden)", "aspect_rank", 1, 5),
            ])
        ]
    },
    {
        "title": "Familiars",
        "groups": [
            ("Frinos the Frog", [
                ("FrogBondLevel", "Frinos Bond Level (1-5)", "familiar_rank", 1, 5),
                ("FrogUnlocked", "Recruited / Unlocked", "familiar_bool", 0, 1),
                ("FrogHealthBonus", "Maximum Health Perk Level", "familiar_rank", 1, 5),
                ("FrogBlockMissiles", "Block Projectiles Perk Level", "familiar_rank", 1, 5),
            ]),
            ("Toula the Cat", [
                ("CatBondLevel", "Toula Bond Level (1-5)", "familiar_rank", 1, 5),
                ("CatUnlocked", "Recruited / Unlocked", "familiar_bool", 0, 1),
                ("CatRevive", "Extra Death Defiance Perk Level", "familiar_rank", 1, 5),
                ("CatDamageClaw", "Claw Strike Attack Perk Level", "familiar_rank", 1, 5),
                ("CatFishingFish", "Bonus Fishing Catches Perk Level", "familiar_rank", 1, 5),
            ]),
            ("Raki the Raven", [
                ("RavenBondLevel", "Raki Bond Level (1-5)", "familiar_rank", 1, 5),
                ("RavenUnlocked", "Recruited / Unlocked", "familiar_bool", 0, 1),
                ("RavenPeckCrit", "Critical Chance Perk Level", "familiar_rank", 1, 5),
                ("RavenCollectSeeds", "Auto Forage & Seeds Perk Level", "familiar_rank", 1, 5),
            ]),
            ("Gale the Polecat", [
                ("PolecatBondLevel", "Gale Bond Level (1-5)", "familiar_rank", 1, 5),
                ("PolecatUnlocked", "Recruited / Unlocked", "familiar_bool", 0, 1),
                ("PolecatDodgeSpeed", "Dodge & Sprint Perk Level", "familiar_rank", 1, 5),
                ("PolecatResourceSniff", "Resource Sniffer Perk Level", "familiar_rank", 1, 5),
            ]),
            ("Beast Loyalty & Treats", [
                ("SuperGiftPoints", "Witch's Delight (Beast Treats)", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Relationships",
        "groups": [
            ("Crossroads Residents (Affinity & Hearts)", [
                ("NPC_Hecate_01", "Headmistress Hecate", "gift_tier", 0, 10),
                ("NPC_Odysseus_01", "Odysseus", "gift_tier", 0, 10),
                ("NPC_Dora_01", "Dora the Shade", "gift_tier", 0, 10),
                ("NPC_Nemesis_01", "Nemesis (Retribution)", "gift_tier", 0, 10),
                ("NPC_Moros_01", "Moros (Doom)", "gift_tier", 0, 10),
                ("NPC_Eris_01", "Eris (Strife)", "gift_tier", 0, 10),
                ("NPC_Charon_01", "Charon the Boatman", "gift_tier", 0, 10),
                ("NPC_Skelly_01", "Commander Schelemeus (Skelly)", "gift_tier", 0, 10),
                ("NPC_Chronos_01", "Chronos (Titan of Time)", "gift_tier", 0, 10),
                ("NPC_Arachne_01", "Arachne the Weaver", "gift_tier", 0, 10),
                ("NPC_Narcissus_01", "Narcissus", "gift_tier", 0, 10),
                ("NPC_Echo_01", "Echo the Nymph", "gift_tier", 0, 10),
                ("NPC_Medea_01", "Medea", "gift_tier", 0, 10),
                ("NPC_Circe_01", "Circe the Sorceress", "gift_tier", 0, 10),
                ("NPC_Icarus_01", "Icarus", "gift_tier", 0, 10),
                ("NPC_Artemis_01", "Artemis (Huntress)", "gift_tier", 0, 10),
                ("NPC_Heracles_01", "Heracles", "gift_tier", 0, 10),
                ("NPC_Selene_01", "Selene (Moon)", "gift_tier", 0, 10),
                ("NPC_Hermes_01", "Hermes (Messenger)", "gift_tier", 0, 10),
                ("NPC_Chaos_01", "Primordial Chaos", "gift_tier", 0, 10),
            ]),
            ("Gift Items & Indulgences", [
                ("GiftPointsCommon", "Nectar", "res", 0, 999),
                ("GiftPointsRare", "Ambrosia", "res", 0, 999),
                ("BathSalt", "Bath Salts (Hot Springs)", "res", 0, 999),
                ("TwinLure", "Twin Lures (Fishing Pier)", "res", 0, 999),
                ("BathingGifts", "Herbal Tea (Taverna)", "res", 0, 999),
                ("BlindBoxPoints", "Obol Points", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Oath & Fear",
        "groups": [
            ("Vows of the Night (Pacts of Punishment)", [
                ("EnemyDamageShrineUpgrade", "Vow of Blood (Enemy Damage +20%/Rank)", "shrine_vow", 0, 3),
                ("EnemyHealthShrineUpgrade", "Vow of Dominance (Enemy Health +10%/Rank)", "shrine_vow", 0, 3),
                ("HealingReductionShrineUpgrade", "Vow of Scars (Healing Reduction -25%/Rank)", "shrine_vow", 0, 3),
                ("EnemySpeedShrineUpgrade", "Vow of Frenzy (Enemy Move & Attack Speed)", "shrine_vow", 0, 3),
                ("EnemyCountShrineUpgrade", "Vow of Hordes (Enemy Pack Density)", "shrine_vow", 0, 3),
                ("ShopPriceShrineUpgrade", "Vow of Arrogance (Shop Price Increase)", "shrine_vow", 0, 3),
                ("EnemyShieldShrineUpgrade", "Vow of Barrier (Enemy Blue Armor Shields)", "shrine_vow", 0, 3),
                ("BoonRerollShrineUpgrade", "Vow of Forsaking (Boon Choices Banished)", "shrine_vow", 0, 3),
                ("TimeLimitShrineUpgrade", "Vow of Desperation (Strict Room Timer)", "shrine_vow", 0, 3),
                ("BiomeSpeedShrineUpgrade", "Vow of Panic (Faster Hazard Timers)", "shrine_vow", 0, 3),
                ("ManaBurnShrineUpgrade", "Vow of Hubris (Magick Cost Prime)", "shrine_vow", 0, 3),
                ("SpawnMinionShrineUpgrade", "Vow of Haunting (Revenant Spirits)", "shrine_vow", 0, 3),
            ])
        ]
    },
    {
        "title": "Cauldron & Incantations",
        "groups": [
            ("Crossroads Infrastructure Incantations", [
                ("WorldUpgradeTaverna", "Woodland Cleansing (Taverna / Bar)", "world_upgrade", 0, 1),
                ("WorldUpgradeBathHouse", "Spring of Purity (Hot Springs)", "world_upgrade", 0, 1),
                ("WorldUpgradeFishingPier", "Watery Haven (Fishing Pier)", "world_upgrade", 0, 1),
                ("WorldUpgradeFountainChambers", "Fonts of Cleansing (Fountain Rooms)", "world_upgrade", 0, 1),
                ("WorldUpgradeAltars", "Attunement of the Altar (Expanded Grasp)", "world_upgrade", 0, 1),
                ("WorldUpgradeShadowExtraction", "Extraction of Shadow (Cauldron Alchemy)", "world_upgrade", 0, 1),
                ("WorldUpgradeAutoHarvestOnExit", "Greatest Gift of Gaia (Auto Harvest)", "world_upgrade", 0, 1),
            ]),
            ("Surface & Boss Difficulty Incantations", [
                ("WorldUpgradeSurfaceWards", "Permeating Modiste (Survive Surface Curse)", "world_upgrade", 0, 1),
                ("WorldUpgradeBossDifficultyT2", "Rivals of Depth and Sea (Scylla T2)", "world_upgrade", 0, 1),
                ("WorldUpgradeBossDifficultyT3", "Rivals of Plain and Peak (Cerberus T3)", "world_upgrade", 0, 1),
                ("WorldUpgradeBossDifficultyT4", "Rivals of Old and Rot (Chronos T4)", "world_upgrade", 0, 1),
            ])
        ]
    },
    {
        "title": "Garden",
        "groups": [
            ("Seeds & Harvest Spores", [
                ("PlantFNightshadeSeed", "Nightshade Seeds", "res", 0, 999),
                ("PlantGLotusSeed", "Lotus Seeds", "res", 0, 999),
                ("PlantHMyrtleSeed", "Myrtle Seeds", "res", 0, 999),
                ("PlantIShaderotSeed", "Shaderot Spores", "res", 0, 999),
                ("PlantJCattailSeed", "Cattail Seeds", "res", 0, 999),
                ("PlantKWheatSeed", "Wheat Seeds", "res", 0, 999),
                ("PlantLPoppySeed", "Poppy Seeds", "res", 0, 999),
                ("PlantMAlgaeSeed", "Algae Spores", "res", 0, 999),
                ("PlantNGarlicSeed", "Garlic Tubers", "res", 0, 999),
                ("PlantFMolySeed", "Moly Seeds", "res", 0, 999),
                ("PlantFMandrakeSeed", "Mandrake Seeds", "res", 0, 999),
                ("PlantFThalamusSeed", "Origin Seeds", "res", 0, 999),
            ]),
            ("Harvested Flora", [
                ("PlantFNightshade", "Nightshade", "res", 0, 999),
                ("PlantGLotus", "Lotus", "res", 0, 999),
                ("PlantHMyrtle", "Myrtle", "res", 0, 999),
                ("PlantIShaderot", "Shaderot", "res", 0, 999),
                ("PlantJCattail", "Cattail", "res", 0, 999),
                ("PlantKWheat", "Wheat", "res", 0, 999),
                ("PlantLPoppy", "Poppy", "res", 0, 999),
                ("PlantMAlgae", "Algae", "res", 0, 999),
                ("PlantNGarlic", "Garlic", "res", 0, 999),
                ("PlantFMoly", "Moly", "res", 0, 999),
                ("PlantFMandrake", "Mandrake", "res", 0, 999),
                ("PlantFThalamus", "Thalamus", "res", 0, 999),
            ])
        ]
    },
    {
        "title": "Fish Catches",
        "groups": [
            ("Underworld Catches", [
                ("FishFCommon", "Moper (Erebus)", "res", 0, 99),
                ("FishFRare", "Figment (Erebus)", "res", 0, 99),
                ("FishFLegendary", "Soulbelly (Erebus)", "res", 0, 99),
                ("FishGCommon", "Chiton (Oceanus)", "res", 0, 99),
                ("FishGRare", "Gutterpop (Oceanus)", "res", 0, 99),
                ("FishGLegendary", "Stalkfin (Oceanus)", "res", 0, 99),
                ("FishHCommon", "Soby (Fields)", "res", 0, 99),
                ("FishHRare", "Anguish (Fields)", "res", 0, 99),
                ("FishHLegendary", "Tearjerker (Fields)", "res", 0, 99),
                ("FishICommon", "Jiffy (Tartarus)", "res", 0, 99),
                ("FishIRare", "Goldfish (Tartarus)", "res", 0, 99),
                ("FishILegendary", "Styxeon (Tartarus)", "res", 0, 99),
            ]),
            ("Surface & Chaos Catches", [
                ("FishNCommon", "Ribeye (Ephyra)", "res", 0, 99),
                ("FishNRare", "Zeel (Ephyra)", "res", 0, 99),
                ("FishNLegendary", "Neckbiter (Ephyra)", "res", 0, 99),
                ("FishOCommon", "Shrimp (Thessaly)", "res", 0, 99),
                ("FishORare", "Chrab (Thessaly)", "res", 0, 99),
                ("FishOLegendary", "Squid (Thessaly)", "res", 0, 99),
                ("FishPCommon", "Pillartop (Olympus)", "res", 0, 99),
                ("FishPRare", "Chrestle (Olympus)", "res", 0, 99),
                ("FishPLegendary", "Starsailor (Olympus)", "res", 0, 99),
                ("FishChaosCommon", "Mati (Chaos)", "res", 0, 99),
                ("FishChaosRare", "Projelly (Chaos)", "res", 0, 99),
                ("FishChaosLegendary", "Voidskate (Chaos)", "res", 0, 99),
            ])
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
        from PySide6.QtWidgets import QMenu, QStackedWidget
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ------------------------------------------------------------- Top Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.file_label = QLabel("Save File: (none)")
        self.file_label.setStyleSheet("font-weight: 600; color: #333;")
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
            self.fix_tex_btn = QPushButton("Fix Textures [HD: ...]")
            self.fix_tex_btn.clicked.connect(self._open_fix_textures)
            top_bar.addWidget(self.fix_tex_btn)
            self._update_fix_texture_btn()

        # Quick Presets Menu (Clean text only)
        preset_btn = QPushButton("Quick Presets")
        preset_menu = QMenu(self)

        act_mat = preset_menu.addAction("+10 All Materials")
        act_mat.triggered.connect(lambda: self._batch_add_resources(10))

        act_curr = preset_menu.addAction("+1,000 All Currencies")
        act_curr.triggered.connect(lambda: self._batch_add_currencies(1000))

        preset_menu.addSeparator()

        act_arc = preset_menu.addAction("Max All Arcana Cards (Rank 3)")
        act_arc.triggered.connect(self._batch_max_arcana)

        act_asp = preset_menu.addAction("Max All Weapon Aspects (Rank 5)")
        act_asp.triggered.connect(self._batch_max_aspects)

        act_fam = preset_menu.addAction("Max All Familiars (Rank 5 & Unlocked)")
        act_fam.triggered.connect(self._batch_max_familiars)

        act_rel = preset_menu.addAction("Max All Relationships (10 Hearts)")
        act_rel.triggered.connect(self._batch_max_affinity)

        act_inc = preset_menu.addAction("Complete All Incantations")
        act_inc.triggered.connect(self._batch_unlock_incantations)

        preset_btn.setMenu(preset_menu)
        top_bar.addWidget(preset_btn)

        save_btn = QPushButton("Save Changes")
        save_btn.setStyleSheet("background-color: #2b78e4; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px;")
        save_btn.clicked.connect(self._save_file)
        top_bar.addWidget(save_btn)

        root.addLayout(top_bar)

        # ------------------------------------------------------------- Master-Detail Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left Navigation Sidebar (Clean text only)
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #d0d7de;
                border-radius: 6px;
                background-color: #f6f8fa;
                padding: 4px;
            }
            QListWidget::item {
                padding: 9px 12px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
                color: #24292f;
                margin-bottom: 2px;
            }
            QListWidget::item:hover {
                background-color: #eaeef2;
            }
            QListWidget::item:selected {
                background-color: #2b78e4;
                color: white;
                font-weight: bold;
            }
            """
        )

        self.stacked_pages = QStackedWidget()

        for idx, sec in enumerate(self.sections):
            item = QListWidgetItem(sec["title"])
            self.sidebar.addItem(item)

            page_widget = self._build_section_page(sec)
            self.stacked_pages.addWidget(page_widget)

        self.sidebar.currentRowChanged.connect(self.stacked_pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stacked_pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

    def _build_section_page(self, sec: Dict[str, Any]) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 0, 0, 0)
        page_layout.setSpacing(8)

        # Section Header with Search Bar
        hdr = QHBoxLayout()
        title_lbl = QLabel(f"<b><span style='font-size: 15px; color: #1f2328;'>{sec['title']}</span></b>")
        hdr.addWidget(title_lbl)
        hdr.addStretch(1)

        search_edit = QLineEdit()
        search_edit.setPlaceholderText(f"Search {sec['title']}...")
        search_edit.setFixedWidth(220)
        search_edit.setClearButtonEnabled(True)
        hdr.addWidget(search_edit)
        page_layout.addLayout(hdr)

        # Scrollable Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(12)
        container_layout.setContentsMargins(0, 0, 6, 0)

        card_widgets_list = []

        for group_title, items in sec["groups"]:
            gb = QGroupBox(group_title)
            gb.setStyleSheet(
                """
                QGroupBox {
                    font-weight: bold;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    margin-top: 8px;
                    padding-top: 14px;
                    background-color: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                    color: #2b78e4;
                }
                """
            )
            gb_grid = QGridLayout(gb)
            gb_grid.setHorizontalSpacing(10)
            gb_grid.setVerticalSpacing(8)
            gb_grid.setContentsMargins(10, 10, 10, 10)

            # 2-Column Responsive Card Grid: 2 items per row
            for idx, (field_key, display_name, field_type, min_v, max_v) in enumerate(items):
                card = self._build_item_card(field_key, display_name, field_type, min_v, max_v)
                r = idx // 2
                c = idx % 2
                gb_grid.addWidget(card, r, c)
                card_widgets_list.append((display_name.lower(), field_key.lower(), card))

            container_layout.addWidget(gb)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        page_layout.addWidget(scroll, stretch=1)

        # Connect live search filter for this section
        def _filter_cards(text: str):
            query = text.strip().lower()
            for disp_lower, key_lower, card_w in card_widgets_list:
                match = not query or (query in disp_lower) or (query in key_lower)
                card_w.setVisible(match)

        search_edit.textChanged.connect(_filter_cards)
        return page

    def _build_item_card(self, field_key: str, display_name: str, field_type: str, min_v: int, max_v: int) -> QWidget:
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            """
            QFrame {
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                background-color: #fafbfc;
                padding: 4px;
            }
            QFrame:hover {
                border-color: #b0c4de;
                background-color: #f3f6fa;
            }
            """
        )

        c_layout = QHBoxLayout(card)
        c_layout.setContentsMargins(8, 6, 8, 6)
        c_layout.setSpacing(8)

        # Left Info: Display Name + Key
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        name_lbl = QLabel(f"<b>{display_name}</b>")
        name_lbl.setStyleSheet("font-size: 13px; color: #24292f;")
        key_lbl = QLabel(f"<code>{field_key}</code>")
        key_lbl.setStyleSheet("font-size: 11px; color: #6a737d;")
        info_layout.addWidget(name_lbl)
        info_layout.addWidget(key_lbl)
        c_layout.addLayout(info_layout, stretch=1)

        # Right Controls: Value + Adjustment buttons
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(4)

        if field_type in ("aspect_rank", "familiar_rank", "arcana_card"):
            spin = QSpinBox()
            spin.setRange(1, max_v if max_v else 5)
            spin.setValue(1)
            spin.setFixedWidth(52)

            if field_type == "arcana_card":
                chk = QCheckBox("Unlocked")
                self._inputs[field_key] = ("arcana_card", (spin, chk))
                ctrl_layout.addWidget(QLabel("Rank:"))
                ctrl_layout.addWidget(spin)
                ctrl_layout.addWidget(chk)
            else:
                self._inputs[field_key] = (field_type, spin)
                ctrl_layout.addWidget(QLabel("Rank:"))
                ctrl_layout.addWidget(spin)
                max_btn = QPushButton(f"Max ({max_v})")
                max_btn.setFixedWidth(58)
                max_btn.clicked.connect(lambda _, s=spin, mv=max_v: s.setValue(mv))
                ctrl_layout.addWidget(max_btn)

        elif field_type == "gift_tier":
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(0)
            spin.setFixedWidth(50)
            self._inputs[field_key] = (field_type, spin)
            ctrl_layout.addWidget(QLabel("Hearts:"))
            ctrl_layout.addWidget(spin)
            max_btn = QPushButton("Max 10")
            max_btn.setFixedWidth(54)
            max_btn.clicked.connect(lambda _, s=spin: s.setValue(10))
            ctrl_layout.addWidget(max_btn)

        elif field_type == "shrine_vow":
            spin = QSpinBox()
            spin.setRange(0, 3)
            spin.setValue(0)
            spin.setFixedWidth(46)
            self._inputs[field_key] = (field_type, spin)
            ctrl_layout.addWidget(QLabel("Rank:"))
            ctrl_layout.addWidget(spin)
            max_btn = QPushButton("Max 3")
            max_btn.setFixedWidth(50)
            max_btn.clicked.connect(lambda _, s=spin: s.setValue(3))
            ctrl_layout.addWidget(max_btn)

        elif field_type in ("res", "keepsake", "state_num", "header_int", "run_hero", "run_meta"):
            spin = QSpinBox()
            spin.setRange(min_v, max_v)
            spin.setValue(0)
            spin.setFixedWidth(76 if max_v > 1000 else 60)
            self._inputs[field_key] = (field_type, spin)
            ctrl_layout.addWidget(spin)

            deltas = [-10, +10] if max_v >= 100 else [-1, +1]
            for d in deltas:
                btn = QPushButton(f"+{d}" if d > 0 else str(d))
                btn.setFixedWidth(34)
                btn.clicked.connect(lambda _, s=spin, delta=d, mv=max_v, miv=min_v: s.setValue(max(miv, min(mv, s.value() + delta))))
                ctrl_layout.addWidget(btn)

        elif field_type in ("header_bool", "weapon_unlock", "world_upgrade", "familiar_bool"):
            chk = QCheckBox("Active")
            chk.setStyleSheet("font-weight: 500;")
            self._inputs[field_key] = (field_type, chk)
            ctrl_layout.addWidget(chk)

        elif field_type == "header_str":
            line = QLineEdit()
            line.setFixedWidth(130)
            self._inputs[field_key] = (field_type, line)
            ctrl_layout.addWidget(line)

        c_layout.addLayout(ctrl_layout)
        return card


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

        aspect_ranks = game_state.get("WeaponAspectRanks", {})
        familiar_levels = game_state.get("FamiliarLevels", {})
        familiar_status = game_state.get("FamiliarStatus", {})
        gift_data = game_state.get("GiftData", {})
        npc_data = game_state.get("NPCData", {})
        shrine_data = game_state.get("ShrinePointData", {})
        active_pacts = game_state.get("ActivePacts", {})

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
            elif f_type == "aspect_rank":
                val = aspect_ranks.get(field_key, 1)
                widget.setValue(max(1, min(5, int(val))))
            elif f_type == "familiar_rank":
                val = familiar_levels.get(field_key, familiar_status.get(field_key, {}).get("Level", 1) if isinstance(familiar_status.get(field_key), dict) else 1)
                widget.setValue(max(1, min(5, int(val))))
            elif f_type == "familiar_bool":
                unlocked = bool(familiar_status.get(field_key, {}).get("Unlocked", False) if isinstance(familiar_status.get(field_key), dict) else familiar_status.get(field_key, False))
                widget.setChecked(unlocked)
            elif f_type == "gift_tier":
                val = gift_data.get(field_key, {}).get("Value", npc_data.get(field_key, {}).get("Value", 0)) if isinstance(gift_data.get(field_key), dict) else gift_data.get(field_key, 0)
                widget.setValue(max(0, min(10, int(val))))
            elif f_type == "shrine_vow":
                val = shrine_data.get(field_key, active_pacts.get(field_key, 0))
                widget.setValue(max(0, min(3, int(val))))
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

        aspect_ranks = game_state.setdefault("WeaponAspectRanks", {})
        familiar_levels = game_state.setdefault("FamiliarLevels", {})
        familiar_status = game_state.setdefault("FamiliarStatus", {})
        gift_data = game_state.setdefault("GiftData", {})
        shrine_data = game_state.setdefault("ShrinePointData", {})

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
            elif f_type == "aspect_rank":
                aspect_ranks[field_key] = float(widget.value())
                weapons_unlocked[field_key] = True
            elif f_type == "familiar_rank":
                familiar_levels[field_key] = float(widget.value())
            elif f_type == "familiar_bool":
                fam = familiar_status.setdefault(field_key, {})
                if isinstance(fam, dict):
                    fam["Unlocked"] = widget.isChecked()
                else:
                    familiar_status[field_key] = widget.isChecked()
            elif f_type == "gift_tier":
                entry = gift_data.setdefault(field_key, {})
                if isinstance(entry, dict):
                    entry["Value"] = float(widget.value())
                else:
                    gift_data[field_key] = float(widget.value())
            elif f_type == "shrine_vow":
                shrine_data[field_key] = float(widget.value())
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

    def _batch_max_aspects(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "aspect_rank":
                widget.setValue(5)
            elif f_type == "weapon_unlock":
                widget.setChecked(True)

    def _batch_max_familiars(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "familiar_rank":
                widget.setValue(5)
            elif f_type == "familiar_bool":
                widget.setChecked(True)

    def _batch_max_affinity(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "gift_tier":
                widget.setValue(10)

    def _batch_unlock_incantations(self):
        for field_key, (f_type, widget) in self._inputs.items():
            if f_type == "world_upgrade":
                widget.setChecked(True)

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