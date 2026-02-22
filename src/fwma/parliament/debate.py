"""AI Parliament debate engine.

The Parliament consists of a Chair and two Members who engage in
structured multi-round debate to evaluate papers or topics.

Debate flow:
1. Chair opens with topic framing
2. Members argue from different perspectives (rounds)
3. Vote check after each round
4. Chair delivers final verdict with score
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fwma.llm.client import LLMClient
from fwma.core.utils import parse_json_response

logger = logging.getLogger(__name__)


class Parliament:
    """Multi-agent debate system.

    Supports custom AI role assignment:
    - chair_model: model for the chair (e.g., "gemini/gemini-2.5-pro")
    - member1_model: model for member 1
    - member2_model: model for member 2
    """

    def __init__(
        self,
        chair_model: str = "gemini/gemini-2.5-pro",
        member1_model: str = "anthropic/claude-sonnet-4",
        member1_role: str | None = None,
        member1_prompt: str | None = None,
        member2_model: str = "openai/gpt-4o",
        member2_role: str | None = None,
        member2_prompt: str | None = None,
        chair_prompt: str | None = None,
        verdict_prompt: str | None = None,
        use_default_prompts: bool = True,
        prompts_module: Any = None,
    ):
        """Initialize the Parliament.

        Args:
            chair_model: Chair model string (provider/model-name)
            member1_model: Member 1 model string
            member1_role: Short role description for member 1 (embedded in default template)
            member1_prompt: Full custom prompt for member 1 (overrides member1_role)
            member2_model: Member 2 model string
            member2_role: Short role description for member 2
            member2_prompt: Full custom prompt for member 2 (overrides member2_role)
            chair_prompt: Full custom prompt for chair
            verdict_prompt: Verdict prompt template (may contain {rounds} placeholder)
            use_default_prompts: Whether to use default prompts from prompts module
            prompts_module: Prompts module to use (defaults to fwma.prompts.zh)
        """
        self.client = LLMClient()

        self.chair_model = chair_model
        self.member1_model = member1_model
        self.member2_model = member2_model
        self.use_default_prompts = use_default_prompts

        # Load prompts module
        if prompts_module is None:
            from fwma.prompts import zh as prompts_module
        self._prompts = prompts_module

        # Custom prompts (highest priority)
        self.member1_prompt = member1_prompt
        self.member2_prompt = member2_prompt
        self.chair_prompt = chair_prompt
        self.verdict_prompt = verdict_prompt

        # Role descriptions
        if use_default_prompts:
            self.member1_role = member1_role
            self.member2_role = member2_role
        else:
            self.member1_role = member1_role or "工程师议员，实战型ML工程师。关注代码实现和工程可行性"
            self.member2_role = member2_role or "理论议员，严谨的理论研究者。关注理论基础和方法局限性"

    def _call_model(self, model: str, messages: list[dict], system_prompt: str) -> str:
        """Call a model via LLMClient."""
        return self.client.call(model=model, messages=messages, system_prompt=system_prompt)

    def hold_debate(
        self,
        paper_text: str,
        user_requirement: str,
        max_rounds: int = 5,
    ) -> dict:
        """Hold a parliament debate.

        Args:
            paper_text: The paper content to debate
            user_requirement: User's research requirement
            max_rounds: Maximum number of debate rounds

        Returns:
            dict with debate_history, final_verdict, rounds_used
        """
        logger.info("=" * 60)
        logger.info("[Parliament] Starting debate")
        logger.info("  Chair: %s", self.chair_model)
        logger.info("  Member1: %s", self.member1_model)
        logger.info("  Member2: %s", self.member2_model)
        logger.info("=" * 60)

        debate_history: list[dict] = []
        context = f"""
# 论文内容
{paper_text}

# 用户需求
{user_requirement}
"""
        prompts = self._prompts.ParliamentPrompts

        # Chair system prompt
        chair_system_prompt = self.chair_prompt or prompts.CHAIR_SYSTEM_PROMPT

        # Round 1: Chair opening
        logger.info("[Chair] Opening...")
        chair_response = self._call_model(
            self.chair_model,
            messages=[{"role": "user", "content": context}],
            system_prompt=chair_system_prompt,
        )
        chair_data = parse_json_response(chair_response)
        debate_history.append(chair_data)
        logger.info("  %s...", str(chair_data.get("content", ""))[:100])

        # Multi-round debate
        round_num = 0
        for round_num in range(1, max_rounds + 1):
            logger.info("--- Round %d ---", round_num)

            # Member 1 speaks
            logger.info("[Member1 - %s] Speaking...", self.member1_model)
            member1_context = context + "\n\n# 辩论历史\n" + json.dumps(debate_history, ensure_ascii=False, indent=2)

            # Select prompt: full prompt > role template > default
            if self.member1_prompt:
                member1_prompt = self.member1_prompt
            elif self.use_default_prompts and self.member1_role is None:
                member1_prompt = prompts.MEMBER1_ENGINEER_PROMPT
            else:
                member1_prompt = prompts.get_member_system_prompt("议员1", self.member1_role, "member1")

            member1_response = self._call_model(
                self.member1_model,
                messages=[{"role": "user", "content": member1_context}],
                system_prompt=member1_prompt,
            )
            member1_data = parse_json_response(member1_response)

            if not member1_data.get("application_ideas"):
                logger.debug("[Debug] Member1 response missing application_ideas")

            debate_history.append(member1_data)
            logger.info("  Score: %s", member1_data.get("score", "N/A"))
            logger.info("  Vote: %s", "end" if member1_data.get("vote") else "continue")

            # Member 2 speaks
            logger.info("[Member2 - %s] Speaking...", self.member2_model)
            member2_context = context + "\n\n# 辩论历史\n" + json.dumps(debate_history, ensure_ascii=False, indent=2)

            if self.member2_prompt:
                member2_prompt = self.member2_prompt
            elif self.use_default_prompts and self.member2_role is None:
                member2_prompt = prompts.MEMBER2_THEORIST_PROMPT
            else:
                member2_prompt = prompts.get_member_system_prompt("议员2", self.member2_role, "member2")

            member2_response = self._call_model(
                self.member2_model,
                messages=[{"role": "user", "content": member2_context}],
                system_prompt=member2_prompt,
            )
            member2_data = parse_json_response(member2_response)
            debate_history.append(member2_data)
            logger.info("  Score: %s", member2_data.get("score", "N/A"))
            logger.info("  Vote: %s", "end" if member2_data.get("vote") else "continue")

            # Vote check
            member1_vote = member1_data.get("vote", False)
            member2_vote = member2_data.get("vote", False)

            if member1_vote and member2_vote:
                # Chair confirms
                logger.info("[Chair] Both members voted to end. Confirming...")
                vote_context = (
                    context
                    + "\n\n# 辩论历史\n"
                    + json.dumps(debate_history, ensure_ascii=False, indent=2)
                    + "\n\n两位议员都投票结束辩论。请确认是否同意结束，并给出最终裁决。"
                )
                chair_vote_response = self._call_model(
                    self.chair_model,
                    messages=[{"role": "user", "content": vote_context}],
                    system_prompt=chair_system_prompt,
                )
                chair_vote_data = parse_json_response(chair_vote_response)
                debate_history.append(chair_vote_data)

                if chair_vote_data.get("vote", True):
                    logger.info("[Parliament] Debate ended early at round %d", round_num)
                    break
            else:
                # Chair summarizes round
                logger.info("[Chair] Summarizing round %d...", round_num)
                summary_context = (
                    context
                    + "\n\n# 辩论历史\n"
                    + json.dumps(debate_history, ensure_ascii=False, indent=2)
                    + f"\n\n请总结第{round_num}轮辩论，引导下一轮讨论方向。"
                )
                chair_summary = self._call_model(
                    self.chair_model,
                    messages=[{"role": "user", "content": summary_context}],
                    system_prompt=chair_system_prompt,
                )
                chair_summary_data = parse_json_response(chair_summary)
                debate_history.append(chair_summary_data)

        # Generate final verdict
        final_verdict = self._generate_verdict(paper_text, user_requirement, debate_history, max_rounds)

        return {
            "debate_history": debate_history,
            "final_verdict": final_verdict,
            "rounds_used": round_num,
        }

    def _generate_verdict(
        self,
        paper_text: str,
        user_requirement: str,
        debate_history: list[dict],
        max_rounds: int,
    ) -> dict:
        """Chair generates final verdict with score and recommendation."""
        prompts = self._prompts.ParliamentPrompts

        verdict_template = self.verdict_prompt or prompts.VERDICT_PROMPT_TEMPLATE
        verdict_prompt = verdict_template.format(rounds=max_rounds)

        verdict_context = f"""
# 论文内容
{paper_text}

# 用户需求
{user_requirement}

# 完整辩论记录
{json.dumps(debate_history, ensure_ascii=False, indent=2)}
"""
        logger.info("[Chair] Generating final verdict...")
        chair_system_prompt = self.chair_prompt or prompts.CHAIR_SYSTEM_PROMPT

        verdict_response = self._call_model(
            self.chair_model,
            messages=[{"role": "user", "content": verdict_context + "\n\n" + verdict_prompt}],
            system_prompt=chair_system_prompt,
        )
        verdict_data = parse_json_response(verdict_response)

        logger.info("  Recommendation: %s", verdict_data.get("recommendation", "N/A"))
        logger.info("  Score: %s", verdict_data.get("score", "N/A"))

        return verdict_data
