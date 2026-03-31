# Agent for Learning Spanish — SUPERSEDED

> This file is outdated. See `plan.md` for the current plan.

---

I am working through a Spanish learning textbook which will be available to the local environment of the agent. The agents goal is to assist me in working through the textbook at a sustainable pace using various methods for interacting with me. I am still working through these interactions. The agent should use my anthropic subscription as the "engine" for generating learning prompts. I am still uncertain if Claude Code will be necessary. 

The agent will track my progress through the book, capture areas of expertise and areas that need improvement that I can easily query, generate questions that I can respond to, answer with correct answer and helpful tips, and the agent will slowly read in more of the textbook as it determines I have learned the previous section or if I ask to move on or move back. 

The textbook has a lot of great sample problems with answers in the back that it should default to using. I want to generate a document that gives the page numbers for each chapter and the page number of the answers for that section.

I am thinking the primary method of communication with the agent can be some sort of messaging. I would absolutely prefer it to be some kind of internet communication and not SMS/RCS text messaging. It would nice to be dropped a paragraph or linked to a section of the book periodically and then I can ask questions and then be quizzed on the material. I should be able to message and indicate I wanna learn something but also be randomly prompted. 

I expect I will need to have some sort of cron job to achieve this period beahvior. 

## Ground Rules

- The agent or perhaps the LLM should never attempt to parse and process the entire textbook
- ???

## Things I Don't Know

- Where will this agent run?
- Can it handle the periodic thing on its own?
- Do I need Claude Code?
- How do I make sure I don't explode my token usage from Anthropic?
  - I am willing to spend a reasonable amount
-  