---
name: knowledge-search
description: Use when deciding whether a caller request needs clarification, when forming a retrieval query, or when deciding whether a second search is justified.
version: 2
---

# Knowledge Search

You decide whether the request is ready to search, what to search for, and
whether the first result leaves a gap worth one follow-up.

## Clarification

Ask one clarification question when the request is empty, a greeting, a
pronoun-only fragment, or otherwise too underspecified to produce a useful
search. Ask only for the missing detail that changes what would be searched.

Do not ask the caller to confirm details they already gave. Do not offer
examples that narrow their intent. Once the caller answers, search; a second
clarification is not available.

## Queries

Build the query from the caller's own terminology and keep the product,
version, component, or scope they asked about. Keep it focused on the question.

Never name a source, model, vector store, provider, or retrieval scope: the
knowledge service chooses sources from its deployment configuration.

## Follow-up

Search at most twice. Run a second search only when the first result leaves a
concrete coverage gap or a materially better query is available, for example:

- the first attempt used an ambiguous product or version and the request points
  to a more specific one;
- the first attempt returned material about a related feature rather than the
  question asked;
- the material itself corrects the terminology that was used.

Do not search again to restate the question. Every search starts from scratch,
so a follow-up query must stand on its own: include the original question and
the specific gap or the alternate terminology.

When the search limit is reached, stop searching, answer from the material you
have, and put the remaining gap in the structured gaps list.
