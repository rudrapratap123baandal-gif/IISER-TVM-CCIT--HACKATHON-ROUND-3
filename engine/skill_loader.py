"""
Clash Royale Skill & Deck Parser for Autonomous Arena.
Parses non-coder friendly Markdown decks, archetypes, lane preferences,
and generates structured executable tactical triggers and LLM instructions.
"""
import re
import os
from typing import Dict, Any, List, Optional
from engine.config import CARD_CATALOG

def detect_card_from_text(text: str) -> Optional[str]:
    """Bulletproof card recognition handling abbreviations, dots, and synonyms."""
    t = text.lower().strip()
    t_clean = re.sub(r"[^a-z0-9]", "", t)

    if "pekka" in t_clean or "peka" in t_clean:
        return "pekka"
    if "babydragon" in t_clean or "dragon" in t_clean:
        return "baby_dragon"
    if "goblinbarrel" in t_clean or "barrel" in t_clean or "goblin" in t_clean:
        return "goblin_barrel"
    if "hogrider" in t_clean or "hog" in t_clean:
        return "hog_rider"
    if "skeleton" in t_clean or "skarmy" in t_clean:
        return "skeletons"
    if "musket" in t_clean:
        return "musketeer"
    if "archer" in t_clean or "bowman" in t_clean:
        return "archers"
    if "giant" in t_clean or "golem" in t_clean:
        return "giant"
    if "fireball" in t_clean or "spell" in t_clean:
        return "fireball"
    if "knight" in t_clean:
        return "knight"
    return None

def parse_tactical_trigger_rule(raw_line: str) -> Dict[str, Any]:
    """Parses natural language IF-THEN / -> trigger rules into actionable conditions and actions."""
    clean_line = re.sub(r"^\d+[\.\)]\s*", "", raw_line).lstrip("-* ").strip()
    parts = re.split(r"->|then", clean_line, flags=re.IGNORECASE)
    cond_text = parts[0].strip()
    action_text = parts[1].strip() if len(parts) > 1 else clean_line

    cond: Dict[str, Any] = {}
    elixir_m = re.search(r"elixir\s*(?:>=|>|is\s*at\s*least|=)\s*(\d+)", cond_text, re.IGNORECASE)
    if elixir_m:
        cond["min_elixir"] = float(elixir_m.group(1))

    tower_hp_m = re.search(r"(?:tower|hp)\s*(?:<|below|under)\s*(\d+)", cond_text, re.IGNORECASE)
    if tower_hp_m:
        cond["max_tower_hp"] = int(tower_hp_m.group(1))

    if re.search(r"giant|pekka|heavy\s*tank|tank|golem", cond_text, re.IGNORECASE):
        cond["enemy_tank"] = True
    if re.search(r"swarm|skeleton|archer", cond_text, re.IGNORECASE):
        cond["enemy_swarm"] = True
    if re.search(r"left", cond_text, re.IGNORECASE):
        cond["enemy_left"] = True
    if re.search(r"right", cond_text, re.IGNORECASE):
        cond["enemy_right"] = True
    if re.search(r"clear|open|undefended", cond_text, re.IGNORECASE):
        cond["lane_clear"] = True

    action: Dict[str, Any] = {}
    action_card = detect_card_from_text(action_text)
    if action_card:
        action["card"] = action_card

    if "right" in action_text.lower():
        action["lane"] = "right"
    elif "left" in action_text.lower():
        action["lane"] = "left"
    elif "opposite" in action_text.lower() or "counter" in action_text.lower():
        action["lane"] = "opposite"

    return {
        "raw": clean_line,
        "cond": cond,
        "action": action
    }

class ClashSkillProfile:
    def __init__(
        self,
        name: str = "Unknown Commander",
        author: str = "Anonymous",
        war_cry: str = "For the Crown!",
        archetype: str = "balanced",
        deck: Optional[List[str]] = None,
        card_priorities: Optional[Dict[str, float]] = None,
        preferred_lane: str = "balanced",
        triggers: Optional[List[str]] = None,
        parsed_triggers: Optional[List[Dict[str, Any]]] = None,
        taunts: Optional[Dict[str, str]] = None,
        raw_content: str = ""
    ):
        self.name = name
        self.author = author
        self.war_cry = war_cry
        self.archetype = archetype
        self.deck = deck or ["knight", "archers", "giant", "musketeer", "hog_rider", "skeletons", "baby_dragon", "fireball"]
        self.card_priorities = card_priorities or {c: 1.0 / len(self.deck) for c in self.deck}
        self.preferred_lane = preferred_lane
        self.triggers = triggers or ["Deploy win condition at bridge when elixir allows", "Defend enemy tanks with swarms"]
        self.parsed_triggers = parsed_triggers or [parse_tactical_trigger_rule(t) for t in self.triggers]
        self.taunts = taunts or {
            "greeting": "Prepare for battle!",
            "crown": "Another crown for the King!",
            "winning": "Well played!"
        }
        self.raw_content = raw_content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "author": self.author,
            "war_cry": self.war_cry,
            "archetype": self.archetype,
            "deck": self.deck,
            "card_priorities": self.card_priorities,
            "preferred_lane": self.preferred_lane,
            "triggers": self.triggers,
            "parsed_triggers": self.parsed_triggers,
            "taunts": self.taunts
        }

    def generate_system_prompt(self, team_color: str) -> str:
        deck_str = ", ".join([f"{CARD_CATALOG[c]['name']} ({c}: {CARD_CATALOG[c]['elixir']}e)" for c in self.deck if c in CARD_CATALOG])
        triggers_str = "\n".join([f"- Rule: {t}" for t in self.triggers[:4]]) if self.triggers else "- Manage elixir carefully and defend lanes"

        prompt = f"""You are the Autonomous Commander of {self.name} playing {team_color.upper()} in Clash Royale 1v1 Arena!
War Cry: "{self.war_cry}"
Archetype Doctrine: {self.archetype.upper()}
Your Strict 8-Card Deck: {deck_str}
Preferred Lane: {self.preferred_lane.upper()}

YOUR MANDATORY TACTICAL RULES:
{triggers_str}

AVAILABLE ACTIONS PER TICK:
1. "card": choose EXACTLY 1 card from your 8-card deck, or "none" if saving elixir
2. "lane": "left" or "right"
3. "thought": 1 tactical sentence explaining your read of the battlefield
4. "taunt": "{self.war_cry}"

OUTPUT REQUIREMENT:
Respond with ONLY a valid JSON object matching this schema:
{{
  "thought": "Opponent exposed left flank. Deploying win condition as instructed.",
  "card": "{self.deck[0]}",
  "lane": "left",
  "taunt": "{self.war_cry}"
}}
No other text."""
        return prompt.strip()


def parse_clash_skill(content: str) -> ClashSkillProfile:
    name = "Challenger"
    author = "Unknown"
    war_cry = "For the Crown!"
    archetype = "balanced"
    preferred_lane = "balanced"
    deck: List[str] = []
    card_priorities: Dict[str, float] = {}
    triggers: List[str] = []

    lines = content.splitlines()
    current_section = None
    section_texts: Dict[str, List[str]] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        name_m = re.match(r"^#\s*(?:Kingdom\s*Name|Commander\s*Name|Deck\s*Name|Name)\s*:\s*(.+)$", stripped, re.IGNORECASE)
        if name_m:
            name = name_m.group(1).strip()
            continue

        author_m = re.match(r"^#\s*(?:Author|Team|Player(?:\s*[\/&]\s*Author)?|Ruler)\s*:\s*(.+)$", stripped, re.IGNORECASE)
        if author_m:
            author = author_m.group(1).strip()
            continue

        war_m = re.match(r"^#\s*War\s*Cry\s*:\s*[\"']?(.+?)[\"']?$", stripped, re.IGNORECASE)
        if war_m:
            war_cry = war_m.group(1).strip()
            continue

        if stripped.startswith("##"):
            sec = stripped.lstrip("#").strip().lower()
            if "deck" in sec or "card" in sec:
                current_section = "deck"
            elif "strategy" in sec or "doctrine" in sec or "archetype" in sec or "playstyle" in sec:
                current_section = "doctrine"
            elif "trigger" in sec or "rule" in sec:
                current_section = "triggers"
            elif "lane" in sec or "flank" in sec:
                current_section = "lane"
            else:
                current_section = "other"
            section_texts[current_section] = []
            continue

        if current_section:
            section_texts[current_section].append(stripped)

    # 1. Parse Deck & Card Weights
    if "deck" in section_texts:
        for dline in section_texts["deck"]:
            card_id = detect_card_from_text(dline)
            if card_id and card_id in CARD_CATALOG:
                if card_id not in deck:
                    deck.append(card_id)
                # Check for weight percentage
                weight_m = re.search(r"[:=]?\s*(\d+(?:\.\d+)?)\s*%", dline)
                weight = float(weight_m.group(1)) if weight_m else 10.0
                card_priorities[card_id] = weight

    # Deduplicate and ensure exactly 8 cards
    deck = list(dict.fromkeys(deck))
    default_cards = ["knight", "archers", "giant", "musketeer", "hog_rider", "skeletons", "baby_dragon", "fireball", "pekka", "goblin_barrel"]
    for c in default_cards:
        if len(deck) >= 8:
            break
        if c not in deck:
            deck.append(c)
            card_priorities[c] = card_priorities.get(c, 10.0)

    deck = deck[:8]

    # 2. Archetype detection
    doc_text = " ".join(section_texts.get("doctrine", [])).lower()
    if "hog" in doc_text or "cycle" in doc_text:
        archetype = "hog_cycle"
    elif "beatdown" in doc_text or "giant" in doc_text:
        archetype = "beatdown"
    elif "bait" in doc_text or "barrel" in doc_text:
        archetype = "spell_bait"
    elif "pekka" in doc_text or "control" in doc_text:
        archetype = "pekka_control"
    elif "bridge" in doc_text or "rush" in doc_text or "spam" in doc_text:
        archetype = "bridge_spam"

    # 3. Lane detection
    lane_text = " ".join(section_texts.get("lane", [])).lower()
    if "left" in lane_text or "left" in doc_text:
        preferred_lane = "left"
    elif "right" in lane_text or "right" in doc_text:
        preferred_lane = "right"
    else:
        preferred_lane = "balanced"

    # 4. Triggers parsing
    parsed_triggers: List[Dict[str, Any]] = []
    if "triggers" in section_texts:
        for tline in section_texts["triggers"]:
            clean_t = re.sub(r"^\d+[\.\)]\s*", "", tline).lstrip("-* ").strip()
            if clean_t and len(clean_t) > 5:
                triggers.append(clean_t)
                parsed_triggers.append(parse_tactical_trigger_rule(clean_t))

    # Normalize weights
    tot = sum(card_priorities.get(c, 1.0) for c in deck)
    if tot > 0:
        card_priorities = {c: card_priorities.get(c, 1.0) / tot for c in deck}
    else:
        card_priorities = {c: 1.0 / len(deck) for c in deck}

    return ClashSkillProfile(
        name=name,
        author=author,
        war_cry=war_cry,
        archetype=archetype,
        deck=deck,
        card_priorities=card_priorities,
        preferred_lane=preferred_lane,
        triggers=triggers,
        parsed_triggers=parsed_triggers,
        raw_content=content
    )


# Aliases for compatibility
KingdomSkillProfile = ClashSkillProfile
parse_kingdom_skill = parse_clash_skill

def load_kingdom_skill_file(filepath: str) -> ClashSkillProfile:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Skill file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return parse_clash_skill(content)


def list_available_kingdom_skills(skills_dir: str = "skills") -> List[Dict[str, Any]]:
    results = []
    if not os.path.isdir(skills_dir):
        return results

    for fname in sorted(os.listdir(skills_dir)):
        if fname.endswith(".md"):
            fpath = os.path.join(skills_dir, fname)
            try:
                profile = load_kingdom_skill_file(fpath)
                data = profile.to_dict()
                data["filename"] = fname
                data["filepath"] = fpath
                results.append(data)
            except Exception as e:
                results.append({
                    "filename": fname,
                    "filepath": fpath,
                    "name": fname,
                    "error": str(e)
                })
    return results


def validate_kingdom_skill_content(content: str) -> Dict[str, Any]:
    errors = []
    warnings = []
    sections_status = {
        "header_metadata": False,
        "archetype": False,
        "deck": False,
        "lane": False,
        "triggers": False
    }

    if len(content.strip()) < 30:
        errors.append("Skill file is too short (must be at least 30 characters).")

    try:
        profile = parse_clash_skill(content)
        
        has_name = bool(profile.name and profile.name != "Unknown Commander")
        has_author = bool(profile.author and profile.author != "Anonymous")
        has_war_cry = bool(profile.war_cry and profile.war_cry != "For the Crown!")
        if has_name or has_author or has_war_cry:
            sections_status["header_metadata"] = True
        else:
            warnings.append("Header metadata missing or default (Deck Name, Player/Author, War Cry).")

        if profile.archetype:
            sections_status["archetype"] = True

        if len(profile.deck) >= 8:
            sections_status["deck"] = True
        else:
            warnings.append(f"Deck specified {len(profile.deck)} cards; 8 required by 4.1 schema.")

        if profile.preferred_lane in ["left", "right", "balanced"]:
            sections_status["lane"] = True

        if len(profile.triggers) >= 1:
            sections_status["triggers"] = True
        else:
            warnings.append("No tactical triggers (IF-THEN rules) detected.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "sections_status": sections_status,
            "profile": profile.to_dict()
        }
    except Exception as e:
        errors.append(f"Parse error: {str(e)}")
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "sections_status": sections_status,
            "profile": None
        }
