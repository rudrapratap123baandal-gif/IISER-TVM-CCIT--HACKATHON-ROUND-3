"""
Async LLM Commander client for Clash Royale AI Arena.
Ensures matches purely depend on the participants' uploaded skill files:
- Custom tactical triggers and IF-THEN doctrine execution
- Strict adherence to the participant's chosen 8-card roster
- Card priority weighting according to participant percentages
- Lane preferences and authentic participant war cries
"""
import re
import json
import random
import asyncio
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List
from engine.config import OLLAMA_BASE_URL, DEFAULT_MODEL, CARD_CATALOG
from engine.skill_loader import ClashSkillProfile

class LLMCommander:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        timeout: float = 6.0
    ):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def generate_order_async(
        self,
        skill_profile: ClashSkillProfile,
        team: str,
        situational_brief: str
    ) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._generate_order_sync,
            skill_profile,
            team,
            situational_brief
        )

    def _generate_order_sync(
        self,
        skill_profile: ClashSkillProfile,
        team: str,
        situational_brief: str
    ) -> Dict[str, Any]:
        system_prompt = skill_profile.generate_system_prompt(team)
        user_prompt = f"{situational_brief}\n\nRespond with your JSON card deployment:"

        combined_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"

        endpoint = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": combined_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.35,
                "top_p": 0.9,
                "num_predict": 90,
                "num_ctx": 2048,
                "num_thread": 4
            }
        }

        raw_response = ""
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                raw_response = res_json.get("response", "")
        except Exception as e:
            raw_response = f"ERROR: {str(e)}"

        parsed_action = self._sanitize_and_validate(raw_response, skill_profile, situational_brief)
        parsed_action["raw_response"] = raw_response
        return parsed_action

    def _parse_brief_metrics(self, brief: str) -> Dict[str, Any]:
        metrics = {
            "elixir": 5.0,
            "my_left": 1400, "my_right": 1400, "my_king": 2400,
            "opp_left": 1400, "opp_right": 1400, "opp_king": 2400,
            "my_troops_left": [], "my_troops_right": [],
            "opp_troops_left": [], "opp_troops_right": []
        }
        if not brief:
            return metrics

        elixir_m = re.search(r"Your Elixir:\s*(\d+(?:\.\d+)?)", brief)
        if elixir_m:
            try:
                metrics["elixir"] = float(elixir_m.group(1))
            except Exception:
                pass

        m_towers = re.search(r"Your Towers:\s*Left Princess=(\d+)HP,\s*Right Princess=(\d+)HP,\s*King=(\d+)HP", brief)
        if m_towers:
            metrics["my_left"] = int(m_towers.group(1))
            metrics["my_right"] = int(m_towers.group(2))
            metrics["my_king"] = int(m_towers.group(3))

        o_towers = re.search(r"Enemy Towers:\s*Left Princess=(\d+)HP,\s*Right Princess=(\d+)HP,\s*King=(\d+)HP", brief)
        if o_towers:
            metrics["opp_left"] = int(o_towers.group(1))
            metrics["opp_right"] = int(o_towers.group(2))
            metrics["opp_king"] = int(o_towers.group(3))

        opp_tr_m = re.search(r"Enemy Incoming Troops:\s*\d+\s*\((.*?)\)", brief)
        if opp_tr_m:
            items = [t.strip() for t in opp_tr_m.group(1).split(",") if t.strip() and t.strip() != "None"]
            for it in items:
                lane = "right" if "right" in it.lower() else "left"
                card = it.split(" on ")[0].lower().replace(" ", "_")
                metrics[f"opp_troops_{lane}"].append(card)

        my_tr_m = re.search(r"Your Active Troops:\s*\d+\s*\((.*?)\)", brief)
        if my_tr_m:
            items = [t.strip() for t in my_tr_m.group(1).split(",") if t.strip() and t.strip() != "None"]
            for it in items:
                lane = "right" if "right" in it.lower() else "left"
                card = it.split(" on ")[0].lower().replace(" ", "_")
                metrics[f"my_troops_{lane}"].append(card)

        return metrics

    def _tactical_heuristics(self, skill: ClashSkillProfile, brief: str) -> Dict[str, Any]:
        """
        Pure Skill-Driven Decision Engine.
        Directly evaluates the participant's custom Markdown triggers, 8-card roster,
        archetype, and priority weights.
        """
        metrics = self._parse_brief_metrics(brief)
        elixir = metrics["elixir"]
        deck = [c for c in skill.deck if c in CARD_CATALOG]
        preferred_lane = skill.preferred_lane if skill.preferred_lane in ["left", "right"] else ("left" if random.random() < 0.5 else "right")

        opp_left_dead = metrics["opp_left"] <= 0
        opp_right_dead = metrics["opp_right"] <= 0

        # Evaluate custom triggers
        parsed_triggers = getattr(skill, "parsed_triggers", [])
        for trig in parsed_triggers:
            cond = trig.get("cond", {})
            action = trig.get("action", {})
            raw_text = trig.get("raw", "")

            # Check Condition Matches
            cond_met = True

            # Min Elixir check
            if "min_elixir" in cond:
                if elixir < cond["min_elixir"]:
                    cond_met = False

            # Max Tower HP check (e.g. IF enemy Princess Tower HP < 300)
            if cond_met and "max_tower_hp" in cond:
                max_hp = cond["max_tower_hp"]
                tower_in_range = False
                if not opp_left_dead and metrics["opp_left"] <= max_hp:
                    tower_in_range = True
                if not opp_right_dead and metrics["opp_right"] <= max_hp:
                    tower_in_range = True
                if (opp_left_dead or opp_right_dead) and metrics["opp_king"] <= max_hp:
                    tower_in_range = True
                if not tower_in_range:
                    cond_met = False

            # Enemy Tank check (Giant, Pekka, Hog Rider)
            if cond_met and cond.get("enemy_tank"):
                has_tank = False
                for ln in ["left", "right"]:
                    if any(c in ["giant", "pekka", "hog_rider"] for c in metrics[f"opp_troops_{ln}"]):
                        has_tank = True
                        break
                if not has_tank:
                    cond_met = False

            # Enemy Swarm check
            if cond_met and cond.get("enemy_swarm"):
                has_swarm = False
                for ln in ["left", "right"]:
                    if any(c in ["skeletons", "archers"] for c in metrics[f"opp_troops_{ln}"]):
                        has_swarm = True
                        break
                if not has_swarm:
                    cond_met = False

            # Lane Clear check
            if cond_met and cond.get("lane_clear"):
                opp_left_count = len(metrics["opp_troops_left"])
                opp_right_count = len(metrics["opp_troops_right"])
                if opp_left_count > 0 and opp_right_count > 0:
                    cond_met = False

            # Enemy Attacks Lane check
            if cond_met and cond.get("enemy_left"):
                if len(metrics["opp_troops_left"]) == 0:
                    cond_met = False
            if cond_met and cond.get("enemy_right"):
                if len(metrics["opp_troops_right"]) == 0:
                    cond_met = False

            # If all conditions satisfied, execute participant's action!
            if cond_met:
                act_card = action.get("card")
                if not act_card:
                    # Pick highest priority card matching condition
                    act_card = deck[0] if deck else "knight"

                # Verify card is in the team's 8-card deck and affordable
                if act_card in deck and elixir >= CARD_CATALOG[act_card]["elixir"]:
                    # Determine target lane
                    act_lane = action.get("lane")
                    if act_lane == "opposite":
                        act_lane = "right" if len(metrics["opp_troops_left"]) > 0 else "left"
                    elif act_lane not in ["left", "right"]:
                        # Target whichever lane has the threat or preferred lane
                        if len(metrics["opp_troops_left"]) > 0 and not opp_left_dead:
                            act_lane = "left"
                        elif len(metrics["opp_troops_right"]) > 0 and not opp_right_dead:
                            act_lane = "right"
                        else:
                            act_lane = preferred_lane

                    return {
                        "card": act_card,
                        "lane": act_lane,
                        "thought": f"Directive Triggered: \"{raw_text}\" — Deploying {CARD_CATALOG[act_card]['name']} on {act_lane}.",
                        "taunt": skill.war_cry
                    }

        # Direct tower finisher with fireball
        if "fireball" in deck and elixir >= 4.0:
            if not opp_left_dead and metrics["opp_left"] <= 380:
                return {
                    "card": "fireball",
                    "lane": "left",
                    "thought": f"Enemy left Princess Tower in lethal range ({metrics['opp_left']} HP) — Casting Fireball for the Crown!",
                    "taunt": skill.war_cry
                }
            if not opp_right_dead and metrics["opp_right"] <= 380:
                return {
                    "card": "fireball",
                    "lane": "right",
                    "thought": f"Enemy right Princess Tower in lethal range ({metrics['opp_right']} HP) — Casting Fireball for the Crown!",
                    "taunt": skill.war_cry
                }
            if (opp_left_dead or opp_right_dead) and metrics["opp_king"] <= 130:
                target_lane = "left" if opp_left_dead else "right"
                return {
                    "card": "fireball",
                    "lane": target_lane,
                    "thought": f"Enemy King Tower in lethal spell threshold ({metrics['opp_king']} HP). Firing for the 3-Crown KO!",
                    "taunt": "Victory is ours!"
                }

        # Defensive responses
        for lane in ["left", "right"]:
            incoming = metrics[f"opp_troops_{lane}"]
            if incoming:
                has_tank = any(c in ["giant", "pekka", "hog_rider"] for c in incoming)
                has_swarm = any(c in ["skeletons", "archers"] for c in incoming)

                if has_tank:
                    for defense_card in ["pekka", "skeletons", "musketeer", "knight"]:
                        if defense_card in deck and elixir >= CARD_CATALOG[defense_card]["elixir"]:
                            return {
                                "card": defense_card,
                                "lane": lane,
                                "thought": f"Interception order: Deploying {CARD_CATALOG[defense_card]['name']} on {lane} to neutralize incoming tank.",
                                "taunt": skill.war_cry
                            }

                if has_swarm:
                    for splash_card in ["baby_dragon", "fireball"]:
                        if splash_card in deck and elixir >= CARD_CATALOG[splash_card]["elixir"]:
                            return {
                                "card": splash_card,
                                "lane": lane,
                                "thought": f"Area suppression: Deploying {CARD_CATALOG[splash_card]['name']} to eliminate swarm on {lane}.",
                                "taunt": skill.war_cry
                            }

        # Flank counter-attacks
        opp_has_left = len(metrics["opp_troops_left"]) > 0
        opp_has_right = len(metrics["opp_troops_right"]) > 0
        counter_lane = None
        if opp_has_left and not opp_has_right and not opp_right_dead:
            counter_lane = "right"
        elif opp_has_right and not opp_has_left and not opp_left_dead:
            counter_lane = "left"

        if counter_lane:
            for flank_card in ["hog_rider", "goblin_barrel"]:
                if flank_card in deck and elixir >= CARD_CATALOG[flank_card]["elixir"]:
                    return {
                        "card": flank_card,
                        "lane": counter_lane,
                        "thought": f"Flank exploit: Opponent overcommitted. Blitzing {counter_lane} bridge with {CARD_CATALOG[flank_card]['name']}!",
                        "taunt": skill.war_cry
                    }

        # Main push based on archetype
        target_push_lane = "right" if opp_left_dead and not opp_right_dead else ("left" if opp_right_dead and not opp_left_dead else preferred_lane)

        if elixir >= 7.5:
            if skill.archetype in ["beatdown", "balanced"] and "giant" in deck and elixir >= 5.0:
                return {
                    "card": "giant",
                    "lane": target_push_lane,
                    "thought": f"Macro Doctrine: {skill.archetype.upper()} push initiated with Giant on {target_push_lane}.",
                    "taunt": skill.war_cry
                }
            if skill.archetype in ["pekka_control", "control"] and "pekka" in deck and elixir >= 7.0:
                return {
                    "card": "pekka",
                    "lane": target_push_lane,
                    "thought": f"Macro Doctrine: Heavy armor advance with P.E.K.K.A on {target_push_lane}.",
                    "taunt": skill.war_cry
                }
            if "hog_rider" in deck and elixir >= 4.0:
                return {
                    "card": "hog_rider",
                    "lane": target_push_lane,
                    "thought": f"High tempo bridge charge with Hog Rider on {target_push_lane}.",
                    "taunt": skill.war_cry
                }

        # Cycle cheap cards
        if skill.archetype == "cycle" and elixir >= 4.0:
            for cheap in ["skeletons", "archers", "knight"]:
                if cheap in deck and elixir >= CARD_CATALOG[cheap]["elixir"]:
                    return {
                        "card": cheap,
                        "lane": target_push_lane,
                        "thought": f"Cycling {CARD_CATALOG[cheap]['name']} to sustain rotation cadence.",
                        "taunt": skill.war_cry
                    }

        # Hold elixir
        if elixir < 4.5:
            return {
                "card": "none",
                "lane": target_push_lane,
                "thought": f"Pooling elixir ({elixir:.1f}/10) according to {skill.archetype} doctrine.",
                "taunt": ""
            }

        # Fallback weighted pick based on card priorities
        affordable = [c for c in deck if CARD_CATALOG[c]["elixir"] <= elixir]
        if affordable:
            weights = [skill.card_priorities.get(c, 1.0) for c in affordable]
            chosen = random.choices(affordable, weights=weights, k=1)[0]
            return {
                "card": chosen,
                "lane": target_push_lane,
                "thought": f"Deploying {CARD_CATALOG[chosen]['name']} on {target_push_lane} per deck weighting ({skill.card_priorities.get(chosen, 0)*100:.0f}%).",
                "taunt": skill.war_cry
            }

        return {
            "card": "none",
            "lane": target_push_lane,
            "thought": "Holding position and saving elixir reserves.",
            "taunt": ""
        }

    def _sanitize_and_validate(self, text: str, skill: ClashSkillProfile, brief: str = "") -> Dict[str, Any]:
        tactical_order = self._tactical_heuristics(skill, brief)
        deck = [c for c in skill.deck if c in CARD_CATALOG]

        if not text or "ERROR:" in text:
            return tactical_order

        clean_text = text.strip()
        data = None

        try:
            data = json.loads(clean_text)
        except Exception:
            pass

        if not data:
            match = re.search(r"\{[\s\S]*\}", clean_text)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:
                    pass

        if not isinstance(data, dict):
            return self._heuristic_fallback(clean_text, skill, tactical_order)

        result = {}

        # Explicit tactical directive priority: if a participant's rule triggered, preserve it
        if tactical_order.get("thought", "").startswith("Directive Triggered:"):
            result["thought"] = tactical_order["thought"]
            result["card"] = tactical_order["card"]
            result["lane"] = tactical_order["lane"]
            result["taunt"] = tactical_order.get("taunt", skill.war_cry)
            return result

        raw_thought = str(data.get("thought", "")).strip()
        if raw_thought and len(raw_thought) > 10 and not any(bad in raw_thought.lower() for bad in ["json", "format", "here is", "i am an ai"]):
            result["thought"] = raw_thought[:130]
        else:
            result["thought"] = tactical_order["thought"]

        # Validate card strictly against the participant's deck!
        c = str(data.get("card", "none")).lower().strip()
        card_synonyms = {
            "hog": "hog_rider", "hogrider": "hog_rider",
            "dragon": "baby_dragon",
            "archer": "archers",
            "skeleton": "skeletons", "skarmy": "skeletons",
            "barrel": "goblin_barrel"
        }
        c = card_synonyms.get(c, c)

        # Ensure card is STRICTLY inside participant's 8-card deck!
        if c in deck:
            result["card"] = c
        elif c == "none":
            result["card"] = "none"
        else:
            result["card"] = tactical_order["card"]

        # Validate lane
        lane = str(data.get("lane", tactical_order["lane"])).lower().strip()
        result["lane"] = "right" if "right" in lane else "left"

        result["taunt"] = str(data.get("taunt", skill.war_cry))[:100]
        return result

    def _heuristic_fallback(self, text: str, skill: ClashSkillProfile, default: Dict[str, Any]) -> Dict[str, Any]:
        res = dict(default)
        t_low = text.lower()
        deck = [c for c in skill.deck if c in CARD_CATALOG]

        for card_id in deck:
            if card_id in t_low:
                res["card"] = card_id
                break

        if "right" in t_low:
            res["lane"] = "right"
        elif "left" in t_low:
            res["lane"] = "left"

        return res
