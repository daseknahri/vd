# Faceless automation & publishing

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of Aug 2026 the faceless-video space has split into two layers that matter for a self-hosted factory: (1) end-to-end "idea-in, posted-video-out" SaaS (AutoShorts.ai, Revid.ai, Faceless.video, HeyGen Video Agent) that own the whole pipeline and mostly can't be composed into a custom stack, and (2) composable primitives — n8n/Make workflow templates plus unified auto-posting APIs (Blotato, Ayrshare, Upload-Post, Post for Me, Postiz) — that a code-driven pipeline like yours should target instead. The single hardest technical constraint is auto-posting policy, not generation: native TikTok/YouTube/Instagram publishing APIs impose audits, low upload quotas, and per-day caps that unified APIs abstract away (often via draft-mode fallback). Virality/hook prediction became a real product category in 2026, led by Higgsfield's Virality Predictor (hook score + hold rate + brain heatmap), which you already have MCP access to. Most unified posting APIs now ship hosted MCP servers, so an agent-driven pipeline can publish with a single call rather than maintaining 8-11 native OAuth integrations. Pricing for the composable layer is cheap and fixed-cost-friendly ($10-29/mo flat), matching your fixed-cost-first design principle.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [Blotato](https://www.blotato.com/blog/best-social-media-api-tools) | unified auto-posting API | api/paid | ~$29/mo flat | Single API call publishes to X, LinkedIn, Instagram (incl. Reels), TikTok, YouTube, Facebook, Pinterest, Threads, Bluesky; vendor manages all OAuth/app-approval; hosted MCP at mcp.blotato.com/mcp for agent posting |
| [Upload-Post](https://www.upload-post.com/) | unified auto-posting API | api/freemium | Free tier 10 uploads/mo (no card); paid from ~$16/mo billed annually | One call to post/schedule to TikTok, Instagram, YouTube, LinkedIn, Facebook, X, Threads, Pinterest, Reddit, Bluesky (~12-20 platforms); handles OAuth + platform compliance; hosted MCP at mcp.upload-post.com/mcp; agent-native design |
| [Ayrshare](https://www.ayrshare.com/) | unified auto-posting API | api/paid | From ~$149/mo (1 profile) — most expensive of the unified set | 13-14+ networks (TikTok, YouTube, Instagram, FB, LinkedIn, Reddit, Threads, Pinterest, Snapchat, etc.) via single API; ships an MCP server so agents can post; vendor-controlled tokens |
| [Post for Me](https://www.blotato.com/blog/best-social-media-api-tools) | unified auto-posting API | api/paid | From ~$10/mo (1,000 posts) | 9 core platforms, unlimited accounts per tier; notably supports BRING-YOUR-OWN developer credentials for full token ownership (vs vendor-locked tokens) |
| [Postiz](https://www.blotato.com/blog/best-social-media-api-tools) | unified auto-posting API (open-source) | self-hosted/freemium | Free self-hosted; ~$29/mo cloud | Widest coverage (30+ platforms); self-hostable for free (fixed-cost path) or $29/mo cloud; self-managed or vendor OAuth; strong fit for a self-hosted factory |
| [TikTok Content Posting API](https://developers.tiktok.com/doc/content-sharing-guidelines) | native platform posting API | api/free | Free API; audit gate is the cost | Direct Post + draft (PULL_FROM_URL / FILE_UPLOAD). Unaudited clients: SELF_ONLY visibility, max 5 users/24h. Public posting requires passing a separate Content Posting audit (can take weeks). Rate limit 6 req/min per user token; ~15 posts/day/creator shared across all clients |
| [YouTube Data API v3](https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota) | native platform posting API | api/free | Free within quota; extension via Google Cloud form | videos.insert for Shorts/long-form upload. 10,000 quota units/day default; videos.insert costs ~1,600 units => ~6 uploads/day/project before needing a quota-extension request. Resets midnight PT |
| [Instagram Graph API (Meta)](https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/) | native platform posting API | api/free | Free; requires FB Business/Meta app review | Two-step Reels publish: POST container to /{ig-user-id}/media then /{ig-user-id}/media_publish. Content-publishing cap commonly cited as 25 posts/24h/account (some 2026 sources report 50 or 100); Reels+Stories share the bucket. BUC rate formula 4800xImpressions/24h |
| [Higgsfield Virality Predictor](https://pasqualepillitteri.it/en/news/2273/higgsfield-virality-predictor-hook-score-hold-rate-2026) | virality/hook prediction | api/paid (MCP available) | unknown (bundled in Higgsfield plans) | Analyzes clips up to ~15s; returns Virality Index, Hook Strength (first-second attention), Hold Rate, and a 'brain heatmap'. You already have Higgsfield MCP connected. Company ~$300M annualized run rate by Feb 2026 |
| [Go Viral / quso.ai Virality Score / Otto](https://www.go-viral.app/) | virality/hook prediction | freemium/paid | freemium | Pre-post 0-100 scoring of hook, watch-time potential, storytelling, pacing, trend alignment, retention; quso and Otto tune per-platform (Shorts/Reels/TikTok) |
| [n8n (faceless-shorts templates)](https://n8n.io/workflows/8290-automate-faceless-shorts-with-openai-runwayml-and-elevenlabs-script-to-social-media/) | workflow automation / orchestration | self-hosted/free (open source) | Free self-hosted; cloud tiers extra | Free self-hostable orchestrator with many public faceless templates: script->TTS->image/video->captions->multi-platform post. Official templates wire OpenAI/Gemini + ElevenLabs + RunwayML/Sora2/Replicate + Shotstack/JSON2Video + YouTube/TikTok/IG upload |
| [JSON2Video / Shotstack](https://n8n.io/workflows/6014-create-faceless-videos-with-gemini-elevenlabs-leonardo-ai-and-shotstack/) | programmatic video render API | api/paid | usage-based (unknown exact 2026 rates) | Cloud, code-driven video assembly (template JSON -> MP4) used as the render backend in many n8n faceless factories; alternative to your local ffmpeg render if you ever need horizontal scale |
| [AutoShorts.ai](https://www.argil.ai/blog/autoshorts-ai-review-2026-features-pricing-and-better-alternatives) | end-to-end faceless SaaS | paid | Starter $19/mo (3/wk), Daily $39/mo (1/day), Hardcore $69/mo (2/day); monthly only, one series/plan | Set-and-forget: pick topic, connect YouTube+TikTok, auto-generates and auto-posts on schedule. Reference for the operator UX/cadence, not composable into a custom stack |
| [Revid.ai](https://flowshorts.app/blog/revid-ai-review) | end-to-end faceless SaaS | paid (credits) | Credit-based, variable per generation | Mass-produce viral shorts; pivoted to 'brainrot' style in 2026. Credit-based (variable cost) and you must download + manually upload — no true auto-post |
| [Faceless.video / HeyGen Video Agent](https://www.heygen.com/blog/best-ai-video-generator-faceless-youtube) | end-to-end faceless SaaS | paid | unknown/subscription | Faceless.video = passive story-sourced faceless YouTube automation. HeyGen Video Agent generates a finished ~3-min explainer in ~4 min, pulling B-roll from Sora 2 / Veo 3.1 with captions+VO |

## Key facts (as researched)

- TikTok Content Posting API: unaudited clients are locked to SELF_ONLY visibility and max 5 posting users/24h; public direct posting requires passing a separate Content Posting audit (weeks). Rate limit 6 requests/min per user token; ~15 posts/day/creator, shared across all API clients.
- YouTube Data API v3: 10,000 quota units/day default; videos.insert costs ~1,600 units => only ~6 uploads/day per Google Cloud project before you must file a quota-extension request. Resets midnight Pacific.
- Instagram Graph API Reels: two-step publish (create media container, then media_publish); daily publish cap most often cited as 25 posts/24h/account (2026 sources conflict — some say 50 or 100); Reels and Stories count against the same cap.
- Unified posting APIs now abstract native limits and mostly ship hosted MCP servers: Blotato (~$29/mo flat, mcp.blotato.com/mcp), Upload-Post (free 10/mo then ~$16/mo, mcp.upload-post.com/mcp), Ayrshare (~$149/mo), Post for Me (~$10/mo, bring-your-own creds), Postiz (free self-hosted / $29 cloud).
- Draft-mode fallback is the standard workaround: most third-party APIs default to pushing a DRAFT the human finishes in-app, sidestepping TikTok's audit — a good fit for your gate-2 human-review design.
- Higgsfield Virality Predictor (you have Higgsfield MCP): analyzes <=15s clips, returns Virality Index, Hook Strength (first second), Hold Rate, and a brain heatmap; Higgsfield ~$300M annualized run rate by Feb 2026.
- n8n is the dominant free/self-hosted orchestrator for 'video factory' templates; official ones chain LLM script -> ElevenLabs TTS -> RunwayML/Sora2/Replicate visuals -> Shotstack/JSON2Video render -> YouTube/TikTok/IG upload.
- End-to-end SaaS pricing anchor: AutoShorts.ai $19/$39/$69 per month for 3/wk, 1/day, 2/day; Revid.ai is credit-based (variable) and requires manual upload.

## Relevance to the video factory

Your pipeline already owns generation (Arabic script, ElevenLabs TTS with word timestamps, Pillow+raqm RTL captions, code-driven ffmpeg render). The missing 'publish' stage (pipeline/publish.py currently only writes post.json and never posts, by Hard Rule 2) is exactly where this research lands. Recommendation: do NOT integrate native TikTok/YouTube/Instagram APIs directly — the TikTok audit gate, YouTube's ~6 uploads/day quota, and IG's two-step + 25/day cap are real friction. Instead target ONE unified API behind your publish stage. For fixed-cost-first, self-hosted Postiz is the strongest match (free, self-hosted, 30+ platforms); if you want zero-ops, Upload-Post (free 10/mo, then ~$16/mo) or Blotato ($29 flat) both ship MCP servers so an agent can publish with one call and both offer draft-mode — which dovetails with your gate-2 human review (push a draft, human confirms in-app, never auto-publish). Keep publish idempotent and behind gate 2 exactly as your contract requires. Separately, wire the Higgsfield Virality Predictor (already MCP-connected) into the review stage as an advisory hook/hold score on the rendered vertical before the human gate — a cheap pre-post signal, not an auto-gate. Watch the recurring-cost line: these publishing APIs are fixed monthly (or free self-hosted), so they don't violate your 'only TTS is variable cost' principle; virality-predictor calls could add variable cost, so meter them. The dub path (DUB.md) publishes the same way — the unified API doesn't care whether the video is original-faceless or a dub.

## Watch list

- TikTok Content Posting audit status/timeline — whether unaudited SELF_ONLY limits or the ~15 posts/day/creator cap change; re-check before relying on direct public posting.
- Instagram/Meta Graph API daily publish cap — 2026 sources conflict (25 vs 50 vs 100 per 24h); confirm current number for your account type before scheduling volume.
- YouTube Data API quota — whether the 10,000-unit default or 1,600-unit videos.insert cost changes; plan a quota-extension request if scaling past ~6 uploads/day.
- Unified-API MCP servers (Blotato, Upload-Post, Ayrshare, Postiz) — verify the hosted MCP endpoints and current pricing directly before wiring into publish.py; MCP availability is new and moving.
- Higgsfield Virality Predictor via its MCP — confirm the actual tool name/params (virality_predictor) and whether calls are metered/credited, since it adds variable cost.
- Postiz self-hosted platform coverage & TikTok/IG connector reliability — self-hosted connectors can lag native API changes; verify TikTok+IG still publish before committing.

## Sources

- <https://www.blotato.com/blog/best-social-media-api-tools>
- <https://www.blotato.com/blog/tiktok-api-pricing>
- <https://www.upload-post.com/>
- <https://www.ayrshare.com/>
- <https://developers.tiktok.com/doc/content-sharing-guidelines>
- <https://www.postpeer.dev/blog/best-tiktok-posting-api>
- <https://zernio.com/blog/tiktok-posting-api>
- <https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota>
- <https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/>
- <https://www.blotato.com/blog/instagram-api-pricing>
- <https://pasqualepillitteri.it/en/news/2273/higgsfield-virality-predictor-hook-score-hold-rate-2026>
- <https://www.go-viral.app/>
- <https://n8n.io/workflows/8290-automate-faceless-shorts-with-openai-runwayml-and-elevenlabs-script-to-social-media/>
- <https://n8n.io/workflows/10455-generate-and-publish-ai-faceless-videos-to-youtube-shorts-using-sora-2/>
- <https://www.argil.ai/blog/autoshorts-ai-review-2026-features-pricing-and-better-alternatives>
- <https://flowshorts.app/blog/revid-ai-review>
- <https://www.heygen.com/blog/best-ai-video-generator-faceless-youtube>
