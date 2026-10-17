# India Trading Models — Full Research & Model Specification Context

This file gives Claude full context on the India stock trading model research and specifications developed in a prior session. Read this entirely before making any suggestions or writing any code. This is the source of truth for all three models.

---

## Who I am
- Non-developer. All instructions must be step-by-step with no assumed coding knowledge.
- When something breaks, explain what went wrong in plain language before giving the fix.
- I prefer to understand *why* something is structured a certain way, not just *what* to type — this eventually handles real money.
- Give one step at a time. Always tell me what output to expect.

---

## The 50 Stock Direction Prediction Metrics

A research-grade taxonomy of 50 metrics for predicting stock directional movement, across 7 categories. These form the raw signal library from which all 3 model signal stacks are drawn.

### Category 1 — Price & Trend (Metrics 1–8)
1. **200-day moving average (MA)** — Signal strength 90%, reliability 92%, lead: weeks–months. Primary regime filter. Price above/below 200-DMA separates bull/bear regimes. Golden cross (50 above 200) and death cross are key events. Works on weekly charts.
2. **50-day moving average** — Signal 82%, reliability 84%, lead: days–weeks. Medium-term trend. Dynamic support/resistance. Consecutive closes below = high-conviction sell signal.
3. **52-week high/low proximity** — Signal 78%, reliability 80%, lead: days–months. Stocks near 52-week highs show forward momentum. The "52-week high effect" is one of the most replicated findings in finance.
4. **Higher highs / higher lows pattern** — Signal 75%, lead: weeks. Structural uptrend definition. Violation of prior swing low = earliest warning of trend breakdown.
5. **Gap analysis** — Signal 70%, lead: days–weeks. Earnings gaps above resistance = continuation signals. ~72% of NSE gaps above 1.5% fill within 5 sessions — India-specific pattern.
6. **Support/resistance levels** — Signal 72%, lead: days–weeks. Prior highs become resistance, prior lows become support. Fourth test of resistance usually breaks through.
7. **Bollinger Bands squeeze** — Signal 68%, lead: days. Narrowing bands = compressed volatility + imminent breakout. Direction determined by first close outside band + volume.
8. **MACD** — Signal 74%, lead: days–weeks. 12 vs 26-day EMA difference. Most powerful with divergence: price new highs but MACD failing to confirm = major warning. Use histogram expansion for entry.

### Category 2 — Volume & Flow (Metrics 9–15)
9. **Volume trend confirmation** — Signal 88%, reliability 86%. Most important volume rule: price moves with expanding volume = confirmed. Declining volume moves = suspect.
10. **On-balance volume (OBV)** — Signal 76%, lead: days–weeks. OBV making new highs while price consolidates = institutional accumulation. OBV diverging negatively = early warning of distribution.
11. **VWAP** — Signal 80%, lead: intraday–days. Institutional benchmark. Price above VWAP = institutional demand. Most useful on high-volume names.
12. **Dark pool / block trade prints** — Signal 82%, lead: days–weeks. Large block trades = institutional conviction. NSE block deal window (8:45–9:00 AM) is particularly informative. Data via NSE daily disclosures.
13. **Accumulation/Distribution line** — Signal 74%, lead: days–weeks. Measures where price closes within daily range, weighted by volume. Divergence from price = leading indicator.
14. **Short interest ratio (days to cover)** — Signal 78%, lead: weeks. High short interest + positive catalyst = powerful short squeeze. Above 20% float with days-to-cover >5 = classic squeeze territory.
15. **Options put/call volume ratio** — Signal 76%, lead: days. Contrarian at extremes. Equity put/call above 1.2 = typically oversold. Below 0.5 = excessive optimism.

### Category 3 — Momentum & Oscillators (Metrics 16–23)
16. **RSI(14)** — Signal 78%, lead: days–weeks. Most powerful signal: price new high but RSI prints lower high = bearish divergence. In uptrend, RSI stays 50–80. Weekly RSI divergence = high-conviction.
17. **Stochastic oscillator** — Signal 70%, lead: days. Slow stochastics (14,3,3) less noisy. Most useful in ranging markets. Bullish: stochastic crosses above 20 after hitting below 20.
18. **Rate of change (ROC) / 12-month momentum** — Signal 74%, lead: days–weeks. 12-month ROC is most academically validated momentum indicator. Jegadeesh & Titman (1993): best 12-month returns outperform next 3–12 months. Standard: 12-1 momentum.
19. **ADX (trend strength)** — Signal 72%, lead: weeks. Measures trend strength, not direction. ADX above 25 = trending. Rising ADX from below 20 through 25 with price confirmation = powerful entry signal.
20. **Williams %R** — Signal 68%, lead: days. Scale 0 to -100. Below -80 = oversold, above -20 = overbought. Useful for timing entries in direction of primary trend.
21. **Ichimoku cloud (Kumo)** — Signal 76%, lead: days–weeks. Price above cloud = bullish. Cloud thickness = support/resistance strength. Triple confirmation: price above cloud + bullish TK cross + Chikou above price.
22. **Commodity Channel Index (CCI)** — Signal 66%, lead: days. Extremes above +100 or below -100 signal overbought/oversold. Zero-line crossovers in direction of primary trend most reliable.
23. **Relative strength vs sector/index** — Signal 86%, reliability 84%, lead: weeks–months. Stock consistently outperforming sector and broad market = institutional accumulation. RS making new 52-week highs before price = ultimate early-entry signal.

### Category 4 — Fundamental (Metrics 24–31)
24. **Earnings revision breadth** — Signal 88%, reliability 86%, lead: weeks–months. When analyst consensus broadly revised upward, institutional models re-price higher. Single most powerful fundamental predictor of 1–6 month returns.
25. **Earnings surprise magnitude (EPS beat %)** — Signal 84%, lead: days–weeks. Stocks beating EPS by >10–15% show post-earnings drift for 60+ days (PEAD effect). Strongest for small/mid-caps. High beat + strong price reaction on day = most powerful setup.
26. **Revenue growth acceleration** — Signal 80%, lead: months–quarters. Accelerating top-line growth is earliest signal of fundamental improvement. 3+ consecutive quarters of acceleration before major moves.
27. **PEG ratio** — Signal 74%, lead: months. Peter Lynch's metric. Below 1 = undervalued relative to growth. Below 0.5 = deeply undervalued. More reliable in steady-growth businesses.
28. **Free cash flow yield** — Signal 78%, lead: months–quarters. FCF yield above 5% = real cash generation. FCF acceleration = catalyst for dividend raises, buybacks, re-rating.
29. **Return on equity (ROE) trend** — Signal 72%, lead: quarters. Rising ROE = improving capital efficiency. Sustained ROE above 20% = quality compounders. Rising ROE + revenue growth more powerful than either alone.
30. **Institutional ownership change** — Signal 82%, lead: weeks–months. New top-decile institutional buyers entering = strongest fundamental signal. Rising fund sponsorship before breakout = ideal.
31. **Insider buying (SEC Form 4 / SEBI disclosures)** — Signal 80%, lead: weeks–months. Cluster buying (3+ insiders within 3-month window) = most significant. Open-market purchases by CEOs/CFOs carry most weight.

### Category 5 — Sentiment & Positioning (Metrics 32–38)
32. **AAII investor sentiment survey** — Signal 76%, lead: days–weeks. Contrarian. Extreme bearish readings (>55% bears) precede strong 6-month returns historically.
33. **Put/call open interest skew (IV skew)** — Signal 78%, lead: days. Extreme skew = institutional hedging demand = contrarian buy. India: weekly Nifty/BankNifty PCR shifts are sharpest signals available.
34. **Short interest as % of float** — Signal 76%, lead: weeks. Above 15–20% = fuel for short squeeze on positive news. High short interest + improving fundamentals = explosive potential.
35. **Hedge fund positioning (13-F / COT)** — Signal 74%, lead: weeks–months. Crowded longs = fragility. Goldman "hedge fund VIP list" proxies this. Crowded names vulnerable to factor unwinds.
36. **News sentiment NLP score** — Signal 72%, lead: hours–days. Management tone on earnings calls highly predictive. Uncertain/hedged language = worse subsequent returns. Used by quant hedge funds.
37. **Google Trends / search volume** — Signal 66%, lead: days. Spikes predict retail buying waves. Sustained uptick over weeks > single spike. Most useful for consumer-facing companies.
38. **CEO/CFO confidence index** — Signal 68%, lead: months. Low CEO confidence = lead indicator of capex pullback and guidance cuts. Confident specific guidance vs hedged vague language = meaningful signal.

### Category 6 — Macro & Intermarket (Metrics 39–45)
39. **Federal/RBI funds rate direction** — Signal 90%, reliability 88%, lead: months–years. "Don't fight the central bank." Rate cutting cycles = strongest bull runs. Growth stocks most sensitive due to long-duration cash flows.
40. **Yield curve shape (2s10s spread)** — Signal 86%, lead: months–years. Inverted yield curve preceded every US recession for 50 years, average lead 12–18 months. India: RBI rate cycle more direct.
41. **Credit spreads (HY vs IG)** — Signal 84%, lead: weeks–months. Widening HY credit spreads precede equity weakness by 2–6 weeks. HY spread above 500bps = recession risk.
42. **ISM / India manufacturing PMI direction** — Signal 80%, lead: months. PMI direction matters more than level. New orders minus inventories sub-index particularly forward-looking.
43. **Dollar index (DXY) / INR direction** — Signal 78%, lead: weeks–months. For India: INR weakness = FII outflows, headwind for markets. INR strengthening = FII inflows. Direct impact on Nifty direction.
44. **India VIX level & direction** — Signal 82%, lead: days–weeks. India VIX >20: market fear extreme, reduce positions. VIX <13 + falling: low fear = full allocation. India VIX mean-reverts faster than US VIX.
45. **Oil price and commodity cycle** — Signal 74%, lead: months. Rising oil hurts India (import-dependent economy) more than US. Direct headwind for INR, current account, and consumer stocks.

### Category 7 — Market Structure & Risk (Metrics 46–50)
46. **Sector rotation / relative sector strength** — Signal 84%, lead: weeks–months. Money rotating defensive → cyclical = risk-on. India cycle: IT → banking → infra → consumer follows semi-predictable pattern.
47. **Advance/decline line (market breadth)** — Signal 82%, lead: weeks. Divergence between index performance and A/D line = most reliable warning of weakening bull market.
48. **New highs vs new lows ratio** — Signal 78%, lead: days–weeks. New highs overwhelming new lows (>4:1) = trend confirmed. Zweig breadth thrust (10:1) = near-perfect buy signal historically.
49. **Beta and correlation to market** — Signal 72%. In risk-on: high-beta leads. Risk-off: low-beta outperforms. Rising cross-asset correlations = institutional deleveraging.
50. **Index rebalancing and inclusion flows** — Signal 76%, lead: days–weeks. Known index additions create predictable, mechanical, price-insensitive demand. Average abnormal returns 3–8% around inclusion. Front-running index events is a documented strategy.

---

## Which Metrics Top Quant Funds Use

### Funds and their primary signals
- **Renaissance Medallion** (39% net CAGR): mean reversion, statistical patterns, microstructure, short-term momentum, sentiment signals, 4–5x leverage. Kelly criterion position sizing.
- **AQR Helix** (17.9% 2024): 12-month momentum, cross-asset trend, value factor, carry.
- **Marshall Wace TOPS** (22.7% 2024): broker flow signals, earnings revisions, price momentum, short interest.
- **Two Sigma Spectrum** (10.9% 2024): ML pattern recognition, NLP/news sentiment, earnings surprise, volume anomalies, alt data (satellite, card spend).
- **CFM Stratus** (14.2% 2024): cross-sectional momentum, mean reversion, volatility signals, sector rotation.
- **Winton Fund** (10.3% 2024): 200-day MA/trend, breakout systems, volatility-adjusted position sizing.

### What all top quant funds share
- Systematic (no discretion): 100%
- Risk-adjusted position sizing: 100%
- Signal combination (not single metric): 100%
- Transaction cost obsession: 98%
- Momentum (some form): 95%
- Earnings/fundamental signals: 85%
- Sentiment/alternative data: 78%

### Signals with highest residual alpha (least crowded, most underused)
- Insider cluster buying (#31) — High edge remaining
- Dark pool / block deal flow (#12) — High edge remaining
- IV skew / options flow (#33) — High edge remaining
- NLP news/concall sentiment (#36) — High edge remaining
- Index rebalancing flows (#50) — High edge remaining
- Ichimoku cloud (#21) — High edge remaining (quants largely ignore)
- Google Trends (#37) — High edge remaining
- CEO/CFO confidence (#38) — High edge remaining

### The 20-signal stack for a 2–4x outperformance fund
**Core 6 (table stakes — every serious fund runs these):**
- 12-month price momentum (#18)
- Earnings revision breadth (#24)
- Post-earnings drift PEAD (#25)
- Relative strength vs sector (#23)
- 200-day MA regime filter (#1)
- Volume confirmation (#9)

**Edge layer (8–10 signals with crowding-adjusted residual alpha):**
- Insider cluster buying (#31)
- Dark pool block prints (#12)
- FCF yield acceleration (#28)
- IV skew (#33)
- OBV divergence (#10)
- Index rebalancing flows (#50)
- Breadth thrust / A/D line (#47, #48)
- Sector rotation timing (#46)
- MACD on weekly timeframe (#8)
- ADX trend strength (#19)

**Proprietary edge layer (what creates 2–4x):**
- Signal combination via ML (not averaging) — non-linear alpha
- Alternative data as lead indicator (satellite, card spend, app downloads)
- Volatility-adjusted Kelly position sizing
- Execution alpha (VWAP routing, dark pool, limit-order-only)
- Regime detection meta-signal (gates entire signal stack by market mode)
- Cross-asset signal contamination (CDS leads equity by 2–3 weeks)

---

## India Benchmark Context

- **Nifty 50 CAGR:** ~12% (primary benchmark)
- **Nifty500 Multicap Momentum Quality 50:** 32.5% CAGR over 5 years
- **Top 6 momentum/alpha funds:** ~59% average over 12 months (1yr bull)
- **2–4x the Nifty 50 means:** targeting 25–50% CAGR
- **2–4x the best quant funds means:** targeting 20–80% annually

---

## The 3 India Trading Models

### Overview
- Building 3 AI-powered trading models for India stocks and ETFs (no mutual funds for now)
- Goal: 2–4x better returns than best-in-class India quant/momentum funds
- End state: run each model at suggested frequency, read score/indicator output, take positions manually
- Flow: paper trade first → real money only after validation gates are met
- Build order: **Model 3 first** (lowest frequency, lowest risk), then Model 2, then Model 1

---

### Model 1 — Swing Trade Engine (Medallion-type)
- **Horizon:** 3–15 trading days
- **Universe:** NSE F&O stocks, liquid midcaps
- **Rebalance:** Daily scan, 2–3 trades/week
- **Benchmark:** Nifty Alpha 50 (~59% 1yr)
- **Target:** 90–120% annual / 4–7% monthly compounded
- **Max drawdown target:** <15%
- **Win rate target:** >58%
- **Avg holding:** 5–8 days
- **ML approach:** LightGBM classifier predicting 5-day forward direction

**14 signals with weights:**

| # | Signal | Weight | India-specific note |
|---|--------|--------|---------------------|
| 1 | VWAP reclaim + hold (15min/hourly) | 12% | Critical on NSE — institutions use VWAP heavily; reclaim after gap-down is high-conviction |
| 2 | Dark pool / block deal prints (BSE+NSE) | 12% | NSE block deal window 8:45–9:00 AM is gold — institutional prints before open predict direction |
| 3 | OBV divergence (3-day) | 10% | Effective in FII-driven stocks where smart money moves before price |
| 4 | IV skew flip (options put/call OI) | 10% | India has weekly Nifty/BankNifty expiries — PCR shifts and OI buildup are sharpest signals |
| 5 | RSI(14) daily — divergence focus | 9% | Use alongside 5-day RSI for confirmation; divergence on midcaps highly reliable |
| 6 | Bollinger squeeze breakout (daily) | 9% | Post-result consolidations create textbook squeezes before next leg |
| 7 | Gap fill probability score | 8% | ~72% of NSE gaps above 1.5% fill within 5 sessions — statistically robust India pattern |
| 8 | FII/DII daily net flow direction | 8% | 3-day cumulative FII net buying = most reliable short-term directional macro signal |
| 9 | MACD histogram direction (daily) | 7% | Use zero-line crossover as confirmation; entry on histogram expansion |
| 10 | Futures basis (premium/discount) | 7% | Futures at deep discount to spot = bearish. Premium widening = bullish institutional buildup |
| 11 | Short-term RS vs Nifty 50 (5-day) | 6% | Stocks holding better than index during dip = institutional accumulation |
| 12 | Delivery % (NSE delivery-based volume) | 6% | NSE publishes daily. >60% delivery on breakout = institutional conviction. <30% = speculative |
| 13 | 50-DMA breach / reclaim | 5% | Reclaiming 50-DMA on above-avg volume + delivery = one of most reliable NSE swing setups |
| 14 | India VIX level + direction | 5% | VIX >20: reduce all swing positions 50%. VIX <13 + falling: full swing allocation |

**Key reinforcing signal pairs:**
- VWAP reclaim + high delivery %: +0.74
- Block deal + OBV divergence: +0.68
- FII net buy + futures premium widening: +0.71
- PCR flip + IV skew change: +0.77
- BB squeeze + RS vs Nifty: +0.65

**Conflicting pairs (lower weight when both fire):**
- RSI overbought + block deal buy: -0.31
- FII selling + futures premium: -0.55
- High India VIX + BB breakout signal: -0.48
- Gap-up open + MACD histogram flat: -0.39

**Entry/exit rules (model-enforced, no discretion):**
- Entry trigger: composite score ≥65/100
- Position size: 1% risk per trade (ATR-based stop), Kelly-adjusted, max 8% per position
- Stop loss: 1.5× ATR(10) below entry — hard rule, no override
- Profit target: 2.5× risk minimum; partial exit at 1.5× (50%), trail stop on remainder
- Time stop: exit if no movement in 5 sessions
- Max open positions: 8 simultaneous, different sectors
- Regime gate: India VIX >20 → hold cash, no new entries

**India-specific regime edge:**
Indian markets show strong mean-reversion after 3+ days of FII net selling (>₹3,000 Cr cumulative). Swing long entries are 40% more successful in first 2 days following reversal from sustained FII outflow.

**Success gates before going live:**
- Win rate >55%
- Avg risk/reward >2.2:1
- Sharpe ratio >1.5
- Max drawdown <18%
- Alpha >30% over Nifty Alpha 50
- OOS vs in-sample degradation <30%
- Correlation to Nifty 50 <0.4

---

### Model 2 — Position Trade Engine
- **Horizon:** 4–16 weeks
- **Universe:** Nifty 500 + sector ETFs
- **Rebalance:** Weekly scan, 2–4 trades/month
- **Benchmark:** Nifty200 Momentum 30 (~61% CAGR 3yr)
- **Target:** 45–70% annual
- **Positions held:** 12–20
- **Avg holding:** 8–12 weeks
- **ML approach:** XGBoost ranker predicting 12-week forward return quintile

**16 signals with weights:**

| # | Signal | Weight | India-specific note |
|---|--------|--------|---------------------|
| 1 | 6M + 12M normalised momentum score | 14% | Exact signal used by NSE Nifty500 Momentum 50 index. Volatility-adjusted: raw return ÷ 26-week std dev. Weight 12M at 60%, 6M at 40% |
| 2 | Quarterly earnings surprise (PAT beat %) | 12% | PEAD on NSE midcaps lasts 40–60 days — longer than US. Beating PAT by >15% is threshold |
| 3 | Analyst EPS revision breadth (3-month) | 11% | India has fewer analysts per stock — single upgrade from Kotak/HDFC/ICICI moves stocks significantly |
| 4 | RS vs sector + Nifty (13-week) | 11% | Must outperform both sector index AND Nifty 500 — dual RS filters to top 15% of universe |
| 5 | Promoter holding change (quarterly) | 9% | SEBI mandates quarterly disclosure. Promoter increasing stake = highest conviction insider signal in India |
| 6 | FII + DII 4-week cumulative sector flow | 8% | Sector-level FII allocation shift = 4–8 week lead indicator. Rotation IT→banking→infra is semi-predictable |
| 7 | 200-DMA reclaim + slope direction | 8% | 200-DMA slope turning positive after flatline = institutional confirmation. Strongest with rising delivery % |
| 8 | Revenue growth acceleration (QoQ) | 7% | 3 consecutive quarters of QoQ revenue acceleration = most reliable pre-breakout fundamental signature |
| 9 | Institutional MF holding increase | 7% | AMFI publishes monthly. New entry by large domestic AMF (SBI, HDFC, ICICI Pru) = strong institutional signal |
| 10 | 52-week high/low breakout + volume | 6% | First close above 52-week high on delivery volume >1.5× 20-day avg = best Indian position trade entry |
| 11 | Sector PMI / GST revenue trend | 4% | GST collections by sector proxy real demand. Auto, consumer, infra sectors map directly to GST data |
| 12 | ADX(14) — trend strength filter | 3% | Gate signal: only enter where ADX >20 and rising. Avoids choppy ranging stocks |

**4-layer filtering funnel:**
- **Layer 1:** Nifty 500 → F&O eligible → liquidity screen (avg turnover >₹50Cr/day)
- **Layer 2:** Top quintile on 6M+12M normalised momentum AND positive RS vs sector
- **Layer 3:** At least 2 of: earnings surprise, analyst revision, revenue acceleration, promoter buying
- **Layer 4:** Gradient boost ML outputs final score 0–100; threshold ≥62 for entry

**India-specific edge — promoter holding:**
Promoter stake creeping up 0.5–1% over 2 quarters, combined with stock near 52-week high, has historically preceded major re-rating moves in Indian mid/smallcaps. SEBI's mandatory disclosure makes this a clean, systematic data source.

**Success gates before going live:**
- Annual return OOS >40% gross
- Sharpe >1.8
- Max drawdown <25%
- Alpha >15% over N200 Momentum 30
- OOS vs in-sample degradation <25%
- Correlation to Nifty 50 <0.55

---

### Model 3 — Multi-year Compounding Engine
- **Horizon:** 2–5 years
- **Universe:** Nifty 500
- **Rebalance:** Semi-annual + event-driven alerts
- **Benchmark:** Nifty500 Multicap MQ50 (32.5% CAGR 5yr)
- **Target:** 35–50% CAGR
- **Portfolio size:** 18–25 stocks
- **Max single position:** 8%
- **ML approach:** Random Forest + scoring; annual review

**15 signals with weights:**

| # | Signal | Weight | India-specific logic |
|---|--------|--------|----------------------|
| 1 | ROE trend (5yr improving, sustained >18%) | 10% | Rising ROE + falling D/E = compounding machine. HDFC Bank, Asian Paints, Titan built on sustained high ROE |
| 2 | Revenue growth CAGR (3–5yr, accelerating) | 10% | India nominal GDP ~12–14%. Companies growing at 2–3× GDP (25–40% CAGR) are in structural tailwind |
| 3 | FCF yield + FCF growth trajectory | 9% | FCF-positive Indian SMIDs are genuinely scarce — they re-rate sharply when market discovers them |
| 4 | Sector tailwind score (govt policy + budget) | 9% | PLI scheme beneficiaries, infra capex recipients, defence indigenisation — budget allocation = direct 3–5yr catalyst |
| 5 | Promoter holding + pledge trend (5yr) | 8% | Pledge >30% = avoid entirely. Pledge declining + stake increasing = highest-quality founder-led compounder |
| 6 | Earnings consistency (no miss in 8 qtrs) | 8% | 8 consecutive quarters of beats + positive guidance = extremely rare pool of ~30–40 stocks at any time |
| 7 | TAM expansion signal (total addressable market) | 7% | Formalisation wave: unorganised → organised. Companies benefiting from this shift have 10+ year runways |
| 8 | PEG ratio (forward, sector-adjusted) | 6% | PEG <1 in India = deeply mispriced. Sector-adjust: IT PEG benchmarks differ from banking |
| 9 | Institutional MF accumulation trend (8 qtrs) | 6% | Domestic MF flows now dwarf FII flows. 8-quarter accumulation = strongest long-term smart money signal |
| 10 | Debt/equity improvement trajectory | 5% | Companies deleveraging rapidly = credit re-rating uplift + operating leverage = step-change re-ratings |
| 11 | ROCE >20% sustained | 5% | Separates durable businesses from cyclical ones. Combine with asset-light model for highest durability |
| 12 | EPS CAGR vs P/E expansion opportunity | 4% | Stock moving from 12x to 25x P/E while growing EPS 30% = 5× return in 3 years |
| 13 | Management quality score (NLP on concalls) | 4% | Conservative guidance with delivery = buy. Overconfident guidance after weak results = red flag |
| 14 | India macro cycle alignment (rate + credit) | 4% | RBI rate cycle + credit growth + capex cycle. Infra/banking/real estate respond most; IT/pharma counter-cyclical |
| 15 | 12-month RS as quality filter tiebreaker | 3% | Among equally-scored fundamentals, stock already showing RS outperformance = institutional validation |

**Three structural India waves — overweight in every regime:**
1. **Formalisation wave:** Unorganised → organised market shift driven by GST, UPI, digital credit. Consumer durables, diagnostics, organised retail, logistics = 10–15 year beneficiaries.
2. **Capex cycle wave:** ₹140 lakh crore infrastructure + defence + PLI capex pipeline over 7 years. Capital goods, defence, power T&D, semiconductors = direct beneficiaries with 5–10yr visibility.
3. **Financialisation wave:** India MF AUM to GDP at 20% vs 120%+ in US. Insurance, AMCs, wealth management, retail brokerages = multi-decade runway as savings shift from gold/FD to financial instruments.

**Success gates before going live:**
- CAGR >28% OOS
- Sharpe >2.0
- Max drawdown <30%
- Alpha >8% over N500 MQ50
- OOS vs in-sample degradation <20%
- Correlation to Nifty 50 <0.65

---

## The 10 India-Only Signals — All 3 Models Must Incorporate These

These are India-specific signals that don't exist in generic/US quant literature. Non-negotiable inclusions:

| # | Signal | Source | Models | Alpha driver |
|---|--------|--------|--------|--------------|
| 1 | NSE delivery-based volume % | NSE EOD report (free) | M1 + M2 | >65% delivery on breakout = 2× more predictive than volume alone |
| 2 | Promoter stake change (SEBI disclosure) | SEBI + BSE filings (free) | M2 + M3 | Most powerful insider signal in India. Quarterly, mandatory, clean data |
| 3 | NSE block deal pre-market window 8:45–9:00 AM | NSE (free) | M1 | Institutional accumulation intent before price reflects it |
| 4 | Futures basis premium/discount to spot | NSE F&O data (free) | M1 + M2 | Persistent premium = institutional delivery buildup. Discount = short pressure |
| 5 | FII/DII daily net flow by sector | NSE daily at 6PM (free) | M1 + M2 | 3-day cumulative FII sector flow = most reliable short-to-medium macro signal |
| 6 | GST collection trend by sector | Govt of India monthly (free) | M2 + M3 | 3-month acceleration precedes equity re-rating by 4–8 weeks |
| 7 | India VIX term structure | NSE options (free) | M1 gate | VIX >22 after spike = contrarian buy. VIX >20 = reduce positions |
| 8 | PLI / govt scheme beneficiary status | Ministry websites + news | M3 | PLI recipients have 5–7yr guaranteed revenue visibility — market underprices in early stages |
| 9 | AMFI monthly new MF holdings entry | AMFI website (free) | M2 + M3 | New entry by large AMF = deep fundamental conviction after 2–3 qtrs of earnings verification |
| 10 | Concall management tone NLP via Claude API | BSE transcripts + Claude API | M3 | Conservative guidance + delivery = buy. Excessive qualifications after miss = wait |

---

## Key Constraints and Requirements (Non-Negotiable)

- **Signal decay monitoring:** Every model self-monitors for signal decay at its own frequency. This is automatic, not manual.
- **Feedback loop:** User logs paper trade and real trade outcomes → model rechecks parameters → self-adjusts signal weights → flags when recalibration needed. This loop runs at:
  - Model 1: weekly review
  - Model 2: monthly review
  - Model 3: semi-annual review
- **Proactive flagging:** Claude proactively flags signal decay and realignment needs — does not wait to be asked.
- **No discretionary overrides in Model 1:** All entries/exits system-generated.
- **Circuit breaker:** -8% portfolio drawdown → auto-triggers 50% cash allocation.
- **MF alpha sub-model:** Explicitly excluded for now. Do not build toward it.

---

## Capital Allocation (Target, Once Live)

- **Model 3 (Compounding):** 50% of capital
- **Model 2 (Position):** 35% of capital
- **Model 1 (Swing):** 15% initially → scale to 25% max after 6 months validation

---

## AI Architecture — How Claude Plugs In

### Overall pipeline
```
Data ingestion
→ Feature engineering (all signals computed daily)
→ Regime classifier (Bull / Bear / Choppy / Crisis → adjusts weights)
→ Model scoring (each stock scored 0–100 per model)
→ Portfolio construction (Kelly-sized, sector-limited, correlation-checked)
→ Execution (VWAP-timed, limit orders only, never chase >1.5% gap-up)
```

### ML models
- **Model 1:** LightGBM on 14 signals. Predicts 5-day forward return direction. Walk-forward validation.
- **Model 2:** XGBoost on 16 signals + fundamental data. Predicts 12-week return quintile. Monthly refit.
- **Model 3:** Random Forest + DCF overlay on 15 signals. Annual review cycle. Structural wave score as meta-feature.

### Regime classifier
Meta-model classifies market daily as one of 4 regimes and adjusts signal weights accordingly:
- **Trending bull:** Full momentum weighting
- **Trending bear:** Reduce all positions, increase regime gate sensitivity
- **Choppy:** Reduce momentum weight, increase mean-reversion signals
- **Crisis:** India VIX >25, FII cumulative outflow >₹15,000 Cr in 10 days → 80% cash

### Position sizing
- Kelly fraction = edge/odds, half-Kelly applied
- Correlation-adjusted across positions (no two positions with >0.65 signal correlation)
- ATR-based stops auto-set
- Max portfolio heat: 20% at risk simultaneously

### Anti-overfitting rules
| Risk | Rule |
|------|------|
| Overfitting on backtest | Walk-forward OOS validation only — never test on training data |
| Signal decay | Rolling 6-month feature importance check; if importance drops >50%, reduce weight or remove |
| Human override | Zero discretionary overrides in Model 1; Models 2 and 3 allow 20% discretionary overlay max |
| Drawdown spiral | -8% portfolio → 50% cash auto-triggered; requires separate decision to re-enter |
| Crowding | If 3+ signals correlate to same factor (>0.7), remove lowest-alpha one |

### Claude's role at each build phase

| Phase | What Claude does |
|-------|-----------------|
| Data layer | Writes database schema, ingestion scripts for all data sources, daily sync scheduler |
| Feature engineering | Vectorised pipeline computing all signals daily across all stocks |
| Regime classifier | Classifier labelling each trading day as one of 4 regimes |
| Model training | Trains LightGBM/XGBoost/RF with walk-forward CV, produces OOS metrics and feature importance |
| Backtest engine | Full backtest with QuantStats output: equity curve, Sharpe, drawdown, trade log, benchmark comparison |
| Signal attribution | SHAP value analysis showing per-signal contribution to each trade outcome |
| Weekly review | Given paper trade log → outputs signal performance breakdown, suggested weight adjustments, anomaly detection |
| Concall NLP | Scores earnings call transcripts: confidence 0–10, guidance specificity, risk language density |
| Broker integration | Zerodha Kite Connect order execution wrapper with ATR-based stop auto-placement |
| Daily dashboard | Streamlit dashboard showing today's top ranked stocks per model with scores and signal breakdown |
| Quarterly retrain | Retrains all 3 models with new data, compares vs prior version, flags signal drift |

---

## Train / Validate / Test Splits

| Model | Train | Validate (OOS) | Forward test |
|-------|-------|----------------|--------------|
| Model 1 Swing | Jan 2014 – Dec 2020 | Jan 2021 – Dec 2023 | Jan 2024 – now |
| Model 2 Position | Jan 2013 – Dec 2020 | Jan 2021 – Dec 2023 | Jan 2024 – now |
| Model 3 Compounding | Jan 2010 – Dec 2019 | Jan 2020 – Dec 2023 | Jan 2024 – now |

---

## Build Phases and Sequence

| Phase | Description | Timeline |
|-------|-------------|----------|
| 1 | Data infrastructure — all 12 sources | Weeks 1–2 |
| 2 | Feature engineering pipeline | Weeks 3–4 |
| 3 | Model training + backtesting | Weeks 5–10 |
| 4 | Paper trading shadow mode | Weeks 11–14 |
| 5 | Live deployment — small capital first | Weeks 15–18 |
| 6 | Continuous improvement loop | Ongoing |

### Build order within the 3 models
1. **Model 3 first** — lowest frequency, lowest operational risk, semi-annual rebalance
2. **Model 2 second** — weekly frequency, medium complexity
3. **Model 1 last** — daily operation, highest complexity, deploy only after M2 and M3 stable

### Paper trading gates (must pass before real money)
- **Model 1:** After 50 paper trades, win rate ≥55% and avg RR ≥2.2:1
- **Model 2:** Over 14-week paper period, top-quintile portfolio beats Nifty 500 by ≥15%
- **Model 3:** Semi-annual review shows CAGR tracking ≥28% OOS target

### Step 7 — Paper trading dashboard + feedback loop
The final build step before real money is a feedback interface where:
- User logs the outcome of each paper trade (entry price, exit price, date, which model signal triggered it)
- Model ingests these outcomes and runs attribution analysis: which signals led to wins vs losses
- If a signal's win-rate contribution falls below threshold over rolling 20 trades: model flags it for review
- If flagged: model suggests new weight, tests proposed weight change on historical data, shows comparison
- User approves or rejects the weight adjustment
- This loop runs automatically at each model's review frequency (weekly M1, monthly M2, semi-annual M3)
- Dashboard shows: current signal weights, recent weight changes, signals on watch list for decay, portfolio P&L vs benchmark

---

## Data Sources Summary

| Data | Source | Cost |
|------|--------|------|
| NSE EOD + delivery % | EOD2 Python library | Free |
| India VIX | NSE historical download | Free |
| FII/DII daily flows | nsepython + NSE | Free |
| F&O: PCR, futures basis, OI | EOD2 F&O bhavcopy | Free |
| Block + bulk deals | NSE/BSE daily CSV | Free |
| Promoter holdings | BSE shareholding filings | Free |
| Quarterly financials | Screener.in API | ~₹5–8K/yr |
| Analyst estimates + revisions | Trendlyne or Tijori Finance | ~₹8–15K/yr |
| MF monthly holdings | AMFI website scraper | Free |
| Concall transcripts + NLP | BSE filings + Claude API | ~₹2–4K/mo |
| GST sector data | Govt of India press releases | Free |
| Index constituents history | NSE Indices (point-in-time) | Free |
| **Total running cost** | | **~₹10K/month** |

**Critical:** Must use point-in-time index constituents for backtest — not today's Nifty 500. Survivorship bias will inflate backtest returns by 8–12% if ignored.

---

## Tech Stack

- **Database:** PostgreSQL via Supabase (hosted, free tier)
- **ML:** LightGBM, XGBoost, RandomForest via Python
- **Backtesting:** vectorbt or backtesting.py + QuantStats
- **NLP:** Claude API (claude-sonnet-4-6) for concall tone scoring
- **Broker:** Zerodha Kite Connect (₹2K/mo) or Upstox (free) — not yet chosen
- **Dashboard:** Streamlit
- **Scheduler:** cron job on Mac

