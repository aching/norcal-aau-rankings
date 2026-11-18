#!/usr/bin/env python3
"""Build the three ranking report .md files (11u / 12u / 14u) from fresh boards.

Usage: python3 scripts/build_reports.py

Reads /tmp/rankings/{11u,12u,14u}.md (output of rank_teams.py), takes the
top 15 per board with hand-written Why lines, appends the rest as
volume/tier rows, then Titles + TM-note sections, and writes
/tmp/rep{11,12,14}.md ready for make_pdf.py.

WHYS is keyed by team (not rank) so boards can reshuffle without the
narrative detaching. Always verify a Why against the game log before
reusing it for a new window -- records, margins, and H2H go stale.
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rank_teams import tier_of

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = HERE.parent / "data"

# (cohort, team): why text -- curated from game logs + titles 2026-11-08.
# Stale-window tombstones (verified 2026-11-15, safe to delete once no
# board references them): aiba:11u, gg hawks, 24/8 academy, justhoop
# rise:11u, pma knights:11u, yellow jackets:11u, aiba:12u, nbba:12u,
# wecompete nation grizzles elite:14u, nation prep:14u, old 4-game-entrant
# and duplicate-duckett/nbba blocks below.
WHYS = {

    ("11u", "stockton heroes:11u"):
        "7-2 open (last 9): buried Madera Kings 60-12, beat Chuck Hayes 45-31; Aug forfeit-age loss to GGH-No Shows. Thin regional sample at #15 -- prove it.",
    ("11u", "team locked in david:11u"):
        "9-1 (last 10): APT 17-10, Bay City EB Red 40-22, Lakeshow Niyi 43-42. Soft-4-0-contemporary case: zero ranked wins. Stale-dated (9/26) to #16.",
    ("11u", "one on one gold:11u"):
        "7-8 gold: fresh 11/7-8 D1 sweep (DeMaestri 25-12, Bay Players, BGA Harvey 34-32) + August Fuca split. Losing record vs ranked schedule at #17.",
    ("11u", "bmg prospects:11u"):
        "6-7: Jules loss (24-39), WHPH/SportStrong double (11/7); buried Cruisers, beat iSkill. Negative vs ranked at #18.",
    ("11u", "stl black:11u"):
        "6-2: buried Rebels 15-0, split OTD pair (21-32, 10-34 two days apart); Tracy/Bay rebouts. Untested (sos 0.046), margin (+11.9) says real at #19.",
    ("11u", "lakeshow flitter:11u"):
        "9-4 girls-side: 11/7 sweep (Wildcats 37-6, Novas Sola); Valkyries pair the only blemishes. Climbing to #20.",
    ("12u", "bmg prospects:12u"):
        "7-8: merged history (SV Soldiers renamed mid-season, user-confirmed); fresh form is two November silver losses (NorCal Elite 34-35, BullDawgs 42-51). At #41 on a .500 record with no signature.",
    ("12u", "sj mavs:12u"):
        "3-1 headlined by 41-39 over Fury Elite (9/20) plus an MBA split. Stale (nothing since 9/20) but the H2H keeps them at #21.",
    ("12u", "bay area stars:12u"):
        "8-7 national crucible .500: beat NBBA, SF Champs; lost to AIBA by 3, PMA. Fresh 10/24-25 split with BMG Soldiers. Volume + close margins at #26.",
    ("14u", "nation prep:14u"):
        "Inactive (last game 9/13, 8-1): JRP32 3-1 is fully decayed out; the Hawks/AIBA H2Hs live on only as opponents' credit. Off the board -- needs fresh games.",
    ("14u", "stockton hawks:14u"):
        "8-7: September JRP32 H2H over All In (50-39) still the signature; fresh 11/7 14U Gold split (YBA W, Shine L). Margin (+0.5) is the tax on a .500 line at #15.",
    ("11u", "gg hawk hoops jr 3ssb ca:11u"):
        "STALE 11/15: circuit-only (all 5 games in Jr. 3SSB qualifier tid=273271) -- NorCal-gated off the board. Was 5-0 with prestige x1.25.",
    ("11u", "payton's place:11u"):
        "14-1: squeaker run (27-26, 28-27, 32-24, 10/17) + only loss to WHPH (15-31, 9/20). Stale-dated (nothing since 10/17) but volume holds #4.",
    ("11u", "oakland soldiers myles:11u"):
        "10-5: fresh 11/14 split (beat BGA Harvey 69-55, lost Lava 31-47); beat Arsenal KP 57-54, 24/8 3SSB. Two Lava losses cap it.",
    ("11u", "sf whph:11u"):
        "8-4: buried Bay City Select 57-31 head-to-head (11/7) + BMG 42-30; split Oakland Soldiers (31-30 W, 36-37 L). The Payton's-beaters at #5.",
    ("11u", "24/8 academy jr 3ssb:11u"):
        "STALE 11/15: inactive (last game 9/13, 4 games). Was 3-1 with Bay City/Fury wins, Fuca loss; decayed out of the window.",
    ("12u", "bay city 2033:6th"):
        "6-4 gold: beat #1 Peninsula Gold 31-29 head-to-head + twin 2-point splits with Renegades (31-29 W, 29-31 L). Giant-killers, .500, at #8.",
    ("12u", "oakland soldiers ashton:12u"):
        "10-5: fresh 11/14 sweep (BGA Coach B, SportStrong Blue 57-51); split One on One Gold; buried twice by Justhoop Will (26-58, 59-64). At #9.",
    # Level-split + circuit era (Nov 8-9): bare blobs split by division
    ("11u", "justhoop rise jules:11u"):
        "9-0: beat Lava 49-24, BMG Prospects, One on One-Gold, SportStrong twice. The most complete 11U sample -- holds #1.",
    ("11u", "justhoop rise:11u"):
        "8-2: beat Lava 58-27 in May, split One on One Gold. The senior Justhoop side; Jules is the junior.",
    ("11u", "sportstrong:11u"):
        "8-7: fresh 11/7 triple (BMG 34-29, Bay City 42-36, TEA 51-50) + split Fuca head-to-head (35-32). Jules losses (33-61, 34-50) cap it at #9.",
    ("11u", "pma knights:11u"):
        "7-3: beat MBA 41-40, All in Elite Select; 3 close losses. No signature, no embarrassment.",
    ("12u", "one on one gold:12u"):
        "11-4 gold: fresh 11/7-8 split (Turner + Lava wins, Larry loss) + September PMA/Lava/Elite sweep; buried 30-70 by Jules. The level-split's biggest 12U winner at #5.",
    ("12u", "justhoop rise will:12u"):
        "11-4: swept Fury Elite (63-49, 64-44), buried One on One 70-30, buried Ashton twice (58-26, 64-59). H2H flips over Fury AND One on One; only losses are aged December/2025 + Nov-25 -- holds #2.",
    ("12u", "bulldawgs:6th"):
        "14-1 in local 6th Boys (Hoopright, Coastside, Blitz). Undefeated vs soft fields -- the gate caps it at #7.",
    ("12u", "norcal united:12u"):
        "9-6: split Lakeshow Ali (48-44 W, 44-67 L) + Olympic Club Manny; beat Bay City 2033 head-to-head. Playing-up silver note is stale (September); at #11 on the Ali split.",
    ("12u", "bulldawgs 6th:6th"):
        "10-3 mixed boys/girls slate (Flitter, Spartans 6th in girls brackets; Bay City 6th Black loss). Record counts; competition is mixed. At #15.",
    ("12u", "pma knights:12u"):
        "8-7: two Oct blowout losses (12-31, 15-74) sink a decent September (Ashton, Bay Area Stars, CDA, NorCal Elite wins). Recency hurts at #12.",
    ("14u", "fury:14u"):
        "10-1 gold back at #1 on last-12: G365 King of the Town prestige title + November sweep (BMG 60-55, SportStrong, WHPH); lone loss to Duckett (33-57). All In slips to 8-4, reopening the top.",
    ("14u", "wecompete grizzlies gold:14u"):
        "9-3 merged flagship (Gold + Nation Elite + bare, user-confirmed 11/16): 11/7-8 Rumble pair (SportStrong 66-29, All-In UAA 70-55); Sep Fall Classic 15U-Yellow title (Camo 80-46 final) + G365 Gold semi (BMG 60-38, Fury 58-65). Gold band, no national wins -- #3 on merit.",
    ("14u", "all in elite:14u"):
        "8-4 national at #2: SJ Mavs twice (62-30, 31-26) + Paytons split; October Rumble 1-2 (YBA W, Mavs/SWOOSH L) the tax. Still the only national-band resume -- the ceiling everyone else sits under.",
    ("14u", "bmg national:14u"):
        "9-3 open-modal at #5 (gold/up/open mix): November gold split (UAA, WHPH 72-36, NBBA) + 15U road split; final loss to #1 Fury (55-60) earns max consolation. Modal flipped open on the shorter window.",
    ("14u", "renegades:14u"):
        "11-4 + twin titles (City League Gold, Stage Silver/Bronze): beat Peninsula Gold 50-45, Cali Gold 38-30; BMG loss (36-52) the tax. At #5.",
    ("14u", "wecompete nation grizzles elite:14u"):
        "Inactive (last game 9/13, 9-5): the good-losses exhibit (two tight Fury losses + 60-38 BMG burial) is fully decayed out. Off the board -- needs fresh games.",
    ("14u", "lakeshow duckett:14u"):
        "9-1: buried #1 Fury 57-33 head-to-head + Cali Gold 67-51 + BMG Prospects 55-47; lone loss to R.T.T.O. (35-39, 11/7). Best loss-adjusted portfolio outside the top 3 at #4.",
    ("14u", "team unequal marques:14u"):
        "7-2 gold: Fall Extravaganza 14u D1 title; beat Sportstrong twice (49-34, 32-30), Mavs National; losses to Fury Elite + Arsenal. Quietly deep at #6.",
    ("11u", "all in elite:11u"):
        "5-1 open: fresh 11/14-15 International split (Delta Heat 28-21, NorCal Elite 10u 22-17) + October American 3-1 (MBA loss 29-32 the tax). Thin but rising.",
    ("11u", "bay city eb:11u"):
        "6-1 silver at #14: swept Niyi/Spartans/Cali Gold 5th + Just Respect/PMA; lone loss to Delta Heat-Mazur (26-27, 11/7). Best silver record outside the top 10.",
    ("12u", "stl 6th grey:6th"):
        "7-1 silver at #12: swept Westbay/Impact/BullDawgs/Prowlers; lone loss to SV Soldiers Prospects (23-24, 9/13). The silver-band standard.",
    ("12u", "whph:12u"):
        "7-1 open at #14: PBH/Trust/Reign/Esface streak; lone loss to NBBA Black (33-42, 10/4). Quiet fall, loud record.",
    ("14u", "showtime xvi 2031:14u"):
        "7-2 headlined by 51-25 over #2 ALL IN. Fresh 11/7 14U Gold split (Yellow Jackets W, Team Touch 31-35 L). Two blemishes, both close, at #8.",
    ("14u", "paytons place:14u"):
        "6-2 national at #9: beat #2 All In TWICE (29-16, 35-33) + Showtime head-to-head (35-33). Best win portfolio on the board, thin volume.",
    ("14u", "sf sparks:14u"):
        "6-3 girls-side: Super Showcase sweep + Legree burial 41-10 (9/19); Inspire loss 33-50 caps it. At #14.",
    ("14u", "payton's place:14u"):
        "11-4: fresh 10/31 HS-2 sweep (EB Bulldogs, Valley Bulls 43-42) + October 14U Black tear (Vipers 74-29, Arsenal, BGA). Playing-up volume at #16.",
    ("14u", "norcal elite allocco:14u"):
        "6-0 gold, freshest legs (11/14): buried EBA 3SSB 50-41, Ashton 42-29; September sweep (Navy, YBA, Underrated). Small sample, giant efficiency -- debuts #9.",
    ("14u", "team legree:14u"):
        "6-9: H2H over Inspire (33-31, 10/25) headlines the girls showcase sweep; BT silver collapse (four straight 11/7 losses) sinks the line to #18.",
    # 4-game entrants (min-games 4 + shrinkage price short samples fairly)
    # STALE 11/15: aiba:11u (last 9/13), 24/8 academy, justhoop rise:11u,
    # pma knights:11u, yellow jackets:11u, aiba:12u, nbba:12u, stockton
    # hawks:14u old text, nbba:14u old text, duckett:14u old text -- all
    # decayed/inactive or superseded; tombstoned, not deleted yet.
    ("11u", "aiba:11u"):
        "STALE 11/15: inactive (last game 9/13, 4 games). Was 4-0 national with Lava/Elite/Stars/NBBA wins; decayed out.",
    ("12u", "bay area phenoms:12u"):
        "4-0 national: beat #10 Peninsula Gold twice (31-29, 50-35) + SJ Spartans Gold twice. Holds #1 on the crucible weekend -- must sustain it.",
    ("12u", "nbba:12u"):
        "STALE 11/15: inactive (last game 9/13, 10 games). Was 3-1 JRP32 with aiba/CDA/SportStrong wins; decayed out.",
    ("12u", "aiba:12u"):
        "STALE 11/15: inactive (last game 9/13, 4 games). Was 3-1 JRP32 with Champs/CDA/Stars wins; decayed out.",
    ("14u", "stockton hawks:14u"):
        "8-7: September JRP32 H2H over All In (50-39) still the signature; fresh 11/7 14U Gold split (YBA W, Shine L). Margin (+0.5) is the tax on a .500 line at #15.",
    ("14u", "nbba:14u"):
        "5-2 national at #8: September JRP32 4-0 (Vipers, Lyte, Spartans, SportStrong) + 11/7-8 gold split (SportStrong W, Fury/BMG L). Short window, dense quality.",
    ("14u", "lakeshow duckett:14u"):
        "9-1: buried #1 Fury 57-33 head-to-head + Cali Gold 67-51 + BMG Prospects 55-47; lone loss to R.T.T.O. (35-39, 11/7). Best loss-adjusted portfolio outside the top 3 at #4.",
    # 11U
    ("11u", "lakeshow fuca:11u"):
        "10-5: split SportStrong (35-32 W, 32-35 L) + One on One-Gold head-to-head; Bay City 6th Black by 1 (35-34). Squeaker-heavy again -- margin (+6.1) stays flat.",
    ("11u", "bay city select:11u"):
        "10-5 gold: beat ISkill 48-42, swept Renegades/Esface in September; 11/7 double loss (SportStrong 36-42, SF WHPH 31-57) drops them to #6.",
    ("11u", "mba triple threat:11u"):
        "12-3: swept Royal Kings, split All in Elite (32-29 W, 23-29 L). Best sustained win rate on the board at #12.",
    ("11u", "yellow jackets:11u"):
        "STALE 11/15: inactive (last game 9/12, 27 games). Was YBA Rize + margin (+10.1); decayed out.",
    ("11u", "hoopsphere rising steve:11u"):
        "8-3: fresh 10/31 burial of EB Bulldogs (46-8) + EBA squeaker (36-35); two fresh 11/14 BT bronze losses (31-63, 46-49) dent but don't sink it. Untested vs top 5.",
    ("11u", "team united:11u"):
        "14-1, +23.1 (biggest margin on any board) -- but zero top-10 H2Hs in a soft open field. The gate caps dominance without evidence at #7 on volume alone; fresh 11/7 loss to Team Elite Academy (12-25).",
    ("11u", "peninsula gold ua future:11u"):
        "7-5 gold: beat Renegades twice, tarheels twice-removed; swept by Esface (20-33, 22-37). Schedule (0.062) over record at #14.",
    ("11u", "otd:11u"):
        "8-3: fresh 11/7-8 D2 sweep (Marathon 53-19, Chew 52-27, BSB 42-26) + five straight open double-digit wins (10/24-25). Older 2025 forfeit losses aged out of the window; margin (+14.7) is real.",
    ("11u", "lakeshow flitter:11u"):
        "9-4 girls-side: 11/7 sweep (Wildcats 37-6, Novas Sola); Valkyries pair the only blemishes. Climbing to #20.",
    ("11u", "bay area lava:11u"):
        "10-5 gold: fresh 11/14 sweep (Oakland Soldiers-Myles 47-31, SportStrong Black 52-38) + JRP32 national split. Squeaker losses to WHPH (43-45) and Jules (24-49) cap it at #2.",
    ("11u", "bay area wildcats:11u"):
        "9-6 open: three straight fresh losses (Novas, Flitter 37-6, Norcal Force); May volume props up a cold close at #22.",
    ("11u", "whph:11u"):
        "10-5: fresh 11/14 split (beat BGA Harvey 48-47, lost SportStrong Black 39-62); beat Lava 45-43 head-to-head. Squeaker profile, live legs.",
    ("11u", "b bay city select:11u"):
        "5-1 girls-side, +10.3; swept Flight/NP Force, lone loss to BullDawgs 5th. Separate squad from Bay City Select; never blend.",
    ("11u", "lakeshow niyi:11u"):
        "6-9 but fresh 11/7 sweep (Vipers 57-22, Just Respect 39-24); three One-on-One losses + BSB/Delta sting. High sos (0.073) -- played up all window -- at #45.",
    ("11u", "lakeshow flitter:11u"):
        "9-4 girls-side: 11/7 sweep (Wildcats 37-6, Novas Sola); Valkyries pair the only blemishes. Climbing to #20.",
    ("11u", "pma knights:11u"):
        "STALE 11/15: inactive (last game 9/13, 19 games). Was 41-40 over MBA + SF Champs splits; decayed out.",
    # 12U
    ("12u", "fury elite:12u"):
        "11-3: Labor Day title stands, but the October H2H flip (lost twice to Jules 49-63, 44-64) drops them to #3. Margin (+17.4) still best-in-class argument.",
    ("12u", "mba triple threat:12u"):
        "8-5: national split with Peninsula Gold (33-5 W, 26-36 L) + Fury H2H; SF Rumble runner-up. Full-window #4 on a national slate.",
    ("12u", "renegades:12u"):
        "8-7 gold: split Bay City 2033 and STL 6th Black; buried twice by STL Black/Grey (18-40, 15-41) in one October weekend. Margin (-4.1) sinks them to #20.",
    ("12u", "peninsula gold ua future:12u"):
        "7-8 but toughest 12U schedule (sos 0.155): split MBA nationally, split Bay City 2033, beat #4 MBA 36-26. Good-losses case study at #10.",
    ("12u", "lakeshow ali:12u"):
        "11-3 silver: Fall Extravaganza 13u D2 title (playing up) + September Lakeshow/NorCal/Bay City sweep; fresh 10/17-18 7th-silver split. Silver ceiling keeps #6.",
    ("12u", "stl black:12u"):
        "7-1, freshest data on the board (10/25): buried Renegades 40-18, playing up in 13U. One loss (Bay Area Regulators) at #13.",
    ("12u", "bay area phenoms nb jrp32:12u"):
        "New blood, loudest entrance: 4-1 with +18.2 margin, freshest data (11/8). Shrinkage holds them at #16 -- prove it.",
    ("12u", "lakeshow pickney:12u"):
        "9-6: Tip-Off runner-up; buried Bay City 6th Black 71-43, beat ISkill; lost Esface + NB JRP32 H2H (40-56). Earned it at #18.",
    ("12u", "san jose spartans:12u"):
        "6-9: HHH 6th Grade title (March) is ancient history; July gold 0-4 (Chico, KBA x3) sinks the line. Fresh 11/7 split (NorCal Elite W, SportStrong White L). At #37 on volume, not form.",
    ("12u", "pma knights:12u"):
        "8-7: two Oct blowout losses (12-31, 15-74) sink a decent September (Ashton, Bay Area Stars, CDA, NorCal Elite wins). Recency hurts at #12.",
    ("12u", "sv soldiers prospects:12u"):
        "Inactive (last game 5/24, 1-2): May split with Bay Area Stars/Lakeshow Fuca is fully decayed out. Off the board; keep the name for the BMG-merged history below.",
    ("12u", "stl 6th black:6th"):
        "9-6 gold: beat #1 Peninsula Gold 28-25 + Bay City 2033 37-30; two Renegades losses 35-36/39-40 by a point each. Squeaker team at #17.",
    ("12u", "stl grey:12u"):
        "Undefeated 8-0 but untested (sos 0.055): buried Renegades 41-15, DC Finest 58-12. Margin (+18.0) says real; schedule says TBD at #14.",
    ("12u", "bay area mambas:12u"):
        "11-4 open: fresh 11/7 double loss (NorCal Elite, Vipers 16-55); August open volume + January TM/Manteca wins. Soft schedule sinks them to #19.",
    ("12u", "k hoopz:12u"):
        "10-5 girls-side open: fresh 10/24 sweep (UNEQLD Black/White); Bunker losses the blemish. At #30 on girls volume.",
    ("12u", "cda:12u"):
        "8-7 open: fresh 10/24 sweep (Wildcats, Mercado) + September AIBA squeaker (35-36); JRP32 1-3 caps it. The middle-class cutoff at #35.",
    # 14U
    ("14u", "cali-gold:mike-8th"):
        "11-4 gold: swept NorCal United North 3x but buried 67-51 by #4 Duckett and 56-37 by BMG Prospects. The closed loop, exposed, at #12.",
    ("14u", "lakeshow fuca:14u"):
        "12-3: most decorated (G365 New Year's Bash prestige + Memorial Day, double [T]); fresh 10/17-18 JV run (Snipers Jimmy, Hoopright). No top-10 wins; BMG loss (64-65) the only top-10 H2H. At #11.",
    ("14u", "sj mavs:14u"):
        "4-5: beat Paytons 48-30 but lost All In twice + LGS squeaker (30-31); fresh girls-side blowouts (23-37, 6-40) don't count at this level. Thin and cold at #25.",
    ("14u", "paytons place:14u"):
        "6-2 national at #9: beat #2 All In TWICE (29-16, 35-33) + Showtime head-to-head (35-33). Best win portfolio on the board, thin volume.",
    ("14u", "team inspire:14u"):
        "9-1, +20.5 best margin pressure on the board: 11/8 girls sweep (B2B, KHoopz x2) + Legree burial; lone loss to Legree 31-33 (10/25). Thin but terrifying at #7.",
    ("14u", "stockton bulls:14u"):
        "10-5: 4-0 vs MBA Triple Threat + SF Champs burial (29-19); September form, decayed to #29. Only loss that matters: Idaho Premier.",
    ("14u", "sf sparks:14u"):
        "6-3 girls-side: Super Showcase sweep + Legree burial 41-10 (9/19); Inspire loss 33-50 caps it. At #14.",
    ("14u", "sf champs:14u"):
        "4-3: beat #2 All in Elite 47-42 in Jr Power 32 -- a genuine top-10 win. September form, decayed to #10; the American-bracket sweep caps the ceiling.",
    ("14u", "vision edwards black:14u"):
        "12-3, freshest legs (11/7): beat H2G Elite 49-36, Just Respect 35-33; two 10/31 squeaker losses (Team Arsenal x2 by 4 combined). Quietly deep at #17.",
    ("14u", "bmg prospects:14u"):
        "9-6: beat Renegades 52-36 + Cali Gold Mike 56-37 head-to-heads; fresh 11/7 silver split (EMA Gold L, Renegades W). At #20 on real H2Hs.",
    ("14u", "team legree:14u"):
        "6-9: H2H over Inspire (33-31, 10/25) headlines the girls showcase sweep; BT silver collapse (four straight 11/7 losses) sinks the line to #18.",
    ("14u", "peninsula gold ua future:14u"):
        "9-5: City League Gold runner-up (lost Renegades final 55-60); October win over Renegades 60-55. Gate-adjacent at #32.",
    # unranked-but-notable (TM note + fallers)
    ("14u", "sportstrong blue:14u"):
        "6-7: fresh 11/7 gold split (TM Falcons 35-33 W, H2G 37-38 L) + July national 3-0; May silver 1-2. Volume without signature at #52.",
    ("14u", "oakland soldiers camo:14u"):
        "5-2: Fall Classic 15U runner-up (lost WeCompete Gold 46-80); thin + soft at #30.",
    ("14u", "otd:14u"):
        "9-5 girls-side: fresh 11/7 sweep (Sonoma, KHoopz) + October Super Showcase 3-1; May bronze 1-2. Squeaker profile at #51.",
    ("14u", "payton's place:14u"):
        "11-4: fresh 10/31 HS-2 sweep (EB Bulldogs, Valley Bulls 43-42) + October 14U Black tear (Vipers 74-29, Arsenal, BGA). Playing-up volume at #16.",
    ("14u", "norcal elite allocco:14u"):
        "9-0 gold, Hoop Explosion 14u D1 title (11/15): swept Ashton (42-29, 63-38 final), Silicon Soldiers (38-31), EBA 3SSB (50-41) + SportStrong Blue (47-23); September sweep (Navy, YBA, Underrated). Small sample, giant efficiency at #3.",
    ("14u", "norcal elite bitanga:14u"):
        "5-0 open, +29.6 best margin on the board: Battle for the Belt International pair (47-13, 51-19, 11/14) + Hardwood Red run (46-15, 42-4, 32-19, 11/7-8). Soft fields (sos 0.015) -- prove it in gold.",
    ("11u", "lakeshow fuca 5th/:11u"):
        "4-0 Fall Tip-Off 11u Gold title (9/19-20): swept Harrison (64-31), BMG Prospects (43-17), DBC Watts (44-32), DeMaestri (45-38). Perfect gold weekend.",
    ("11u", "dbc ua 5th watts 5th/:11u"):
        "3-1 Fall Tip-Off 11u Gold (9/19-20): buried DeMaestri (51-23), BMG Prospects (36-26), Harrison (43-29); lone loss to Fuca (32-44).",
    ("11u", "delta heat 5th mazur 5th/:11u"):
        "3-0 Fall Tip-Off 11u Silver (9/19-20): Bay City (35-31), Keith (35-28), Niyi burial (60-31). Clean silver sweep.",
    ("12u", "lakeshow ali 6th/:12u"):
        "4-0 Fall Tip-Off 12u Gold title (9/19-20): Turner (57-35), Lynx (65-18), Harris (71-27), 1-on-1 Gold (65-26). Most dominant weekend on the 12U board.",
    ("12u", "1 on 1 gold 6th/:12u"):
        "3-1 Fall Tip-Off 12u Gold (9/19-20): Harris (40-23), Turner (56-45), Lynx (68-22); lone loss to Ali (26-65). Second-best gold resume.",
    ("12u", "bay area phenoms nb jrp32 6th/:12u"):
        "3-0 Fall Tip-Off 12u Silver East (9/19-20): Garske (52-16), SportStrong Blue (46-23), SF Champs Chris (51-50). Unbeaten silver.",
    ("12u", "nbba marin black 6th baker 6th/:12u"):
        "3-0 Fall Tip-Off 12u Silver West (9/19-20): 1-on-1 Black (43-22), Pickney (40-38), Dublin Green (37-35). Three grind wins.",
    ("14u", "bmg prospects 8th/:14u"):
        "4-0 Fall Tip-Off 14u Silver East (9/19-20, B-squad -- not the gold Prospects): Leopards x2 (73-28, 95-52), Bitanga (66-44), EBA Jeremy (51-50). Silver only.",
    ("14u", "norcal elite allocco 8th/:14u"):
        "9-3 gold: Fall Tip-Off 14u Gold 3-1 (Flow Elite 62-26, Grizzlies Black 35-20, Winter 42-37; loss to Fuca 41-43) + September gold sweep (Navy, YBA, Underrated). Allocco B-weekend.",
    ("14u", "delta heat 8th torres 8th/:14u"):
        "3-0 Fall Tip-Off 14u Silver West (9/19-20): EBA Nik (46-23), Anderson (50-29), Duckett (49-38 -- gold scalp). Unbeaten silver.",
    ("11u", "norcal elite harrison:11u"):
        "4-1: Hoop Explosion 11u 3-0 (Marathon 45-17, BGA Black 43-28, Unequal 46-26) + Sep G365 1-1 (1-on-1 Gold 31-29 W, Watts 33-49 L, JustHoop 17-35 L). Fresh winner.",
}

COHORTS = {
    "11u": ("11U", "11u"),
    "12u": ("12U/6th Grade", "12u,6th"),
    "14u": ("14U/8th Grade", "14u,8th"),
}

TM_NOTES = {
    "12u": "TM Griffins (tm:griffins-12u): 32-23 all-time (+1.0), latest 10/24 (21-42 NBBA Turner, 50-57 Ashton). H2H statement over BMG Prospects (63-25, 9/12) but 0-2 in fall gold/silver finals brackets; prestige games 0-2. Separate squad from TM Falcons (14U) -- never blend.",
    "14u": "TM Falcons (tm:falcons-14u): 17-18 all-time (+2.7), latest 11/7: two 14U Gold losses (33-35 Sportstrong Blue, 27-40 Just Respect) + 10/31 Arsenal/WHPH-style split (Dom 39-30 W, Trust 32-28 W). No titles; the Legree burial (54-22, 10/10) is their best win. Separate squad from TM Griffins (12U) -- never blend.",
    "11u": "No curated TM squad at 11U -- Bay City Select (#6) and B Bay City Select (#21) are separate squads; never blend. Team United (#7) is the girls-side outlier: 14-1 vs soft fields, fresh 11/7 loss to Team Elite Academy.",
}


def parse_board(path):
    rows, header, footer = [], [], []
    in_board = False
    for line in open(path):
        if line.startswith("| # |"):
            in_board = True
            continue
        if in_board and line.startswith("|---"):
            continue
        if in_board and line.startswith("| "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cells)
            continue
        if in_board and not line.startswith("|"):
            in_board = False
        if rows:
            footer.append(line)
        else:
            header.append(line)
    return header, rows, footer


def build(cohort):
    title, level = COHORTS[cohort]
    header, rows, footer = parse_board(f"/tmp/rankings/{cohort}.md")
    h_flips = ""
    h_n = str(len(rows))
    for line in header:
        if "h2h tiebreak" in line:
            m = re.search(r"h2h tiebreak \S+ \((.*)\)\s*$", line)
            if m:
                h_flips = m.group(1)
    md = []
    md.append(f"# {title} NorCal AAU Rankings")
    md.append("")
    md.append(f"Active-only (game in last 60 days), last-15 form -- {h_n} ranked.")
    md.append("Score = per-game credit (tier x decay x margin x title x prestige) x opponent strength, iterated 15x.")
    md.append("Tiers nat 1.0 / up .85 / gold .75 / open .5 / silver .5 / bronze .25. Title x1.5 champ wins; prestige x1.25 EVERY win at Made Hoops/G365/OGP.")
    md.append("Margin (new): log curve capped at 25 -- squeaker ~0.85x, median game ~1.0x, 20pts ~1.15x; close losses keep consolation, blowout losses keep ~0.2x.")
    md.append("Ghosts (<9g) give no opponent strength; only prelim top-10 confer transitive credit (beating #13 pays the floor but no boost); published scores shrink by n/(n+8) -- short streaks must be sustained to hold rank.")
    md.append(f"H2H tiebreak (same-level, fresh, max 2-spot swaps): {h_flips}.")
    md.append("[T] = title holder.")
    md.append("")
    md.append("## Board")
    md.append("")
    md.append("| # | Team | Score | W-L | Tier | SOS | Margin | Latest | Why |")
    md.append("|---|------|-------|-----|------|-----|--------|--------|-----|")
    for r in rows:
        idx = int(r[0])
        tid = r[1].replace(" 🏆", "").strip()
        score, wl, tier, sos, margin, latest = r[2], r[3], r[4], r[5], r[7], r[8]
        tag = " [T]" if "🏆" in r[1] else ""
        why = r[9] if len(r) > 9 and r[9].strip() else "No scored games in window."
        md.append(f"| {idx} | {tid}{tag} | {score} | {wl} | {tier} | {sos} | {margin} | {latest} | {why} |")
    # titles
    md.append("")
    md.append("## Titles (* = prestige Made Hoops/G365/OGP)")
    md.append("")
    for line in footer:
        if line.startswith("#   #"):
            m = re.match(r"#\s+#(\d+) (.+?): (champ|runner-up) (.*?) @ (.*?) (★ )?\((\d+/\d+/\d+)\)( https?://\S+)?", line)
            if m:
                star = " *" if m.group(6) else ""
                url = m.group(8) or ""
                band = tier_of(m.group(4))[0].split(":")[0]
                md.append(f"- #{m.group(1)} {m.group(2)}: {m.group(3)} {m.group(4)} [{band}] @ {m.group(5)}{star} ({m.group(7)}){url}")
    md.append("")
    md.append("## TM note")
    md.append("")
    md.append(TM_NOTES[cohort])
    md.append("")
    names = {"11u": "11", "12u": "12", "14u": "14"}
    out = Path(f"/tmp/rep{names[cohort]}.md")
    out.write_text("\n".join(md))
    print(f"wrote {out} ({len(rows)} ranked)")


if __name__ == "__main__":
    for c in ("11u", "12u", "14u"):
        build(c)
