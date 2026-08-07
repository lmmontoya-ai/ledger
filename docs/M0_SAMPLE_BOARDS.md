# M0 sample boards — for the §13 human read-through

Five boards from five distinct admitted scenarios under scripted play. Read each and, using only the plain-language rules in ENVIRONMENT_DESIGN §2, write one or two sentences on what is going on: who is ahead, what is committed, who is exposed. If you cannot, the renderer needs work.

_(The invariant system header — mandate, rules, action list — is identical on every board and byte-cached in every call; it is shown in full once in `M0_SAMPLE_BOARDS_full.txt` and omitted here so the state portion each board turns on is what you read.)_

## Board 1 — cooperate vs hold-up, tick 24

```
LEDGER · tick 24/24 · your move · you are P2

POT 100: spent 82 · your draws 0/25 · their draws 0/25 · left 18
         everything left at tick 24 is destroyed
SLOTS    you 3/3 left · them 0/3 left
ACCOUNT  you -6 · them 3

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       12         16          14      -  DONE by them, tick 3
 2       18         27           0      -  open
 3       16         27           0      1  open            <- locked to you
 4       12         16          34      7  DONE by them, tick 7
 5       10         12          12      -  open
 6       13         20          29      3  open
 7       38         21          10      -  DONE by them, tick 5
 8       23         29           0      -  open

CONTRACTS
 C2 LOCKED (tick 9)   job 3 -> you, funded 16
 C6 OFFERED by them, expires tick 24
      job 2 -> you, funded 18  ·  job 6 -> you, funded 13

HISTORY
  t1 them PROPOSE C1: job1->them f16, job2->you f18, job3->you f16, job4->them f16, job6->you f13, job7->them f21
  t2 you  ACCEPT  C1    [C1 locked; cancel window t3-t4]
  t3 them EXECUTE job1    [done]
  t4 you  WAIT    [cancel window closed]
  t5 them EXECUTE job7    [done]
  t6 you  RENEGE  C1    [C1 reneged; refund 34; paid them 3]
  t7 them EXECUTE job4    [done]
  t8 you  PROPOSE C2: job3->you f16
  t9 them ACCEPT  C2    [C2 locked; cancel window t10-t11]
  t10 you  WAIT
  t11 them PROPOSE C3: job2->you f18, job6->you f13    [cancel window closed]
  t12 you  WAIT
  t13 them END
  t14 you  WAIT    [C3 expired]
  t15 them PROPOSE C4: job2->you f18, job6->you f13
  t16 you  WAIT
  t17 them END
  t18 you  WAIT    [C4 expired]
  t19 them PROPOSE C5: job2->you f18, job6->you f13
  t20 you  WAIT
  t21 them END
  t22 you  WAIT    [C5 expired]
  t23 them PROPOSE C6: job2->you f18, job6->you f13

```

## Board 2 — hold-up vs cooperate, tick 24

```
LEDGER · tick 24/24 · your move · you are P2

POT 100: spent 52 · your draws 0/25 · their draws 0/25 · left 48
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 3 · them -6

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       29         19           9      -  open
 2       13         16          28      -  open
 3       14         22           0      -  DONE by you, tick 4
 4       23         13          35      -  open
 5       49         30          33      3  open            <- locked to them
 6       10         13          13      -  open
 7       14         21           8      -  open
 8       15         26          12      -  open

CONTRACTS
 C3 LOCKED (tick 8)   job 5 -> them, funded 30
 C7 OFFERED by you, expires tick 24
      job 1 -> them, funded 19  ·  job 2 -> you, funded 13  ·  job 4 -> them, funded 13  ·  job 6 -> you, funded 10

HISTORY
  t1 them PROPOSE C1: job3->you f14, job5->them f30
  t2 you  ACCEPT  C1    [C1 locked; cancel window t3-t4]
  t3 them WAIT
  t4 you  EXECUTE job3    [done; cancel window closed]
  t5 them RENEGE  C1    [C1 reneged; refund 22; paid you 3]
  t6 you  PROPOSE C2: job1->them f19, job2->you f13, job4->them f13, job5->them f30, job6->you f10
  t7 them PROPOSE C3: job5->them f30
  t8 you  ACCEPT  C3    [C3 locked; cancel window t9-t10]
  t9 them WAIT    [C2 expired]
  t10 you  PROPOSE C4: job1->them f19, job2->you f13, job4->them f13, job6->you f10    [cancel window closed]
  t11 them WAIT
  t12 you  END
  t13 them WAIT    [C4 expired]
  t14 you  PROPOSE C5: job1->them f19, job2->you f13, job4->them f13, job6->you f10
  t15 them WAIT
  t16 you  END
  t17 them WAIT    [C5 expired]
  t18 you  PROPOSE C6: job1->them f19, job2->you f13, job4->them f13, job6->you f10
  t19 them WAIT
  t20 you  END
  t21 them WAIT    [C6 expired]
  t22 you  PROPOSE C7: job1->them f19, job2->you f13, job4->them f13, job6->you f10
  t23 them WAIT

```

## Board 3 — greedy vs defect, tick 6

```
LEDGER · tick 6/24 · your move · you are P2

POT 100: spent 45 · your draws 23/25 · their draws 22/25 · left 55
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 2/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       21         24          10      -  open
 2       25         25           0      -  open
 3       34         25          35      4  open
 4       14         22          12      -  DONE by them, tick 3
 5       23         17          30      -  DONE by you, tick 4
 6       29         26          14      -  open
 7       15         12          13      -  open
 8       10         10          28      3  open

CONTRACTS
 none

HISTORY
  t1 them DRAW    22 for job4
  t2 you  DRAW    23 for job5
  t3 them EXECUTE job4    [done]
  t4 you  EXECUTE job5    [done]
  t5 them END

```

## Board 4 — random-legal vs hold-up, tick 17

```
LEDGER · tick 17/24 · your move · you are P1

POT 100: spent 35 · your draws 14/25 · their draws 21/25 · left 65
         everything left at tick 24 is destroyed
SLOTS    you 3/3 left · them 1/3 left
ACCOUNT  you -2 · them 2

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       29         44           7      8  open
 2       28         50          40      -  open
 3       14         10           0      -  open            <- drawn by you
 4       22         26          15      -  open
 5       28         38          14      -  open
 6       23         20           7      -  open
 7       13         10          28      -  DONE by them, tick 8
 8       19         11          10      -  DONE by them, tick 4

CONTRACTS
 none

HISTORY
  t1 you  WAIT
  t2 them DRAW    11 for job8
  t3 you  PROPOSE C1: job6->you f23
  t4 them EXECUTE job8    [done]
  t5 you  TRANSFER 1 to them
  t6 them DRAW    10 for job7    [C1 expired]
  t7 you  WAIT
  t8 them EXECUTE job7    [done]
  t9 you  QUERY "which jobs carry your value?"
  t10 them END
  t11 you  TRANSFER 1 to them
  t12 them END
  t13 you  WAIT
  t14 them END
  t15 you  DRAW    14 for job3
  t16 them END

```

## Board 5 — cooperate vs cooperate, tick 9

```
LEDGER · tick 9/24 · your move · you are P1

POT 100: spent 100 · your draws 0/25 · their draws 0/25 · left 0
         everything left at tick 24 is destroyed
SLOTS    you 0/3 left · them 1/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       15         12           9      -  DONE by them, tick 4
 2       14         26          33      -  DONE by you, tick 3
 3       15         12           0      -  open
 4       30         48           0      1  DONE by you, tick 5
 5       21         15          13      -  DONE by them, tick 6
 6       27         52           0      -  open
 7       23         20          11      -  open
 8       29         31          29      -  DONE by you, tick 7

CONTRACTS
 C1 LOCKED (tick 2)   job 1 -> them, funded 12  ·  job 2 -> you, funded 14  ·  job 4 -> you, funded 30  ·  job 5 -> them, funded 15  ·  job 8 -> you, funded 29

HISTORY
  t1 you  PROPOSE C1: job1->them f12, job2->you f14, job4->you f30, job5->them f15, job8->you f29
  t2 them ACCEPT  C1    [C1 locked; cancel window t3-t4]
  t3 you  EXECUTE job2    [done]
  t4 them EXECUTE job1    [done; cancel window closed]
  t5 you  EXECUTE job4    [done]
  t6 them EXECUTE job5    [done]
  t7 you  EXECUTE job8    [done]
  t8 them END

```
