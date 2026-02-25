Live results scraper and meet analysis tool. 

Indoor track meets consist of the following events (Seen on https://flashresults.com/2026_Meets/Indoor/02-26_SEC/index.htm) live results/schedule. 

Day	Start		Thursday Track	Rnd	Start List	Result		Status
Thursday	5:00 PM		Women 200m	Prelims	Start List	Result		Scheduled
Thursday	5:30 PM		Men 200m	Prelims	Start List	Result		Scheduled
Thursday	6:00 PM		Women 5000m	Final	Start List	Result		Scheduled
Thursday	6:25 PM		Men 5000m	Final	Start List	Result		Scheduled
Thursday	6:50 PM		Women DMR	Finals	Start List	Result		Scheduled
Thursday	7:20 PM		Men DMR	Final	Start List	Result		Scheduled
Day	Start		Thursday Field	Rnd	Start List	Result		Status
Thursday	4:00 PM		Women Pole Vault	Final	Start List	Result		Scheduled
Thursday	5:00 PM		Men Long Jump	Finals	Start List	Result		Scheduled
Thursday	5:00 PM		Women Long Jump	Finals	Start List	Result		Scheduled
Day	Start		Friday Track	Rnd	Start List	Result		Status
Friday	4:00 PM		Women Mile	Prelims	Start List	Result		Scheduled
Friday	4:25 PM		Men Mile	Prelims	Start List	Result		Scheduled
Friday	4:50 PM		Women 60m	Prelims	Start List	Result		Scheduled
Friday	5:00 PM		Men 60m	Prelims	Start List	Result		Scheduled
Friday	5:15 PM		Women 400m	Prelims	Start List	Result		Scheduled
Friday	5:40 PM		Men 400m	Prelims	Start List	Result		Scheduled
Friday	6:15 PM		Women 800m	Prelims	Start List	Result		Scheduled
Friday	6:40 PM		Men 800m	Prelims	Start List	Result		Scheduled
Friday	6:55 PM		Women 60m Hurdles	Prelims	Start List	Result		Scheduled
Friday	7:05 PM		Men 60m Hurdles	Prelims	Start List	Result		Scheduled
Day	Start		Friday Field	Rnd	Start List	Result		Status
Friday	11:00 AM		Women Weight	Finals	Start List	Result		Scheduled
Friday	1:30 PM		Men Weight	Finals	Start List	Result		Scheduled
Friday	2:00 PM		Women High Jump	Final	Start List	Result		Scheduled
Day	Start		Saturday Track	Rnd	Start List	Result		Status
Saturday	4:05 PM		Women 1 Mile	Final	Start List	Result		Scheduled
Saturday	4:15 PM		Men 1 Mile	Final	Start List	Result		Scheduled
Saturday	4:25 PM		Women 60m	Final	Start List	Result		Scheduled
Saturday	4:32 PM		Men 60m	Final	Start List	Result		Scheduled
Saturday	4:45 PM		Women 400m	Finals	Start List	Result		Scheduled
Saturday	4:50 PM		Men 400m	Finals	Start List	Result		Scheduled
Saturday	5:00 PM		Women 800m	Final	Start List	Result		Scheduled
Saturday	5:07 PM		Men 800m	Final	Start List	Result		Scheduled
Saturday	5:15 PM		Women 60m Hurdles	Final	Start List	Result		Scheduled
Saturday	5:22 PM		Men 60m Hurdles	Final	Start List	Result		Scheduled
Saturday	5:30 PM		Women 200m	Finals	Start List	Result		Scheduled
Saturday	5:40 PM		Men 200m	Finals	Start List	Result		Scheduled
Saturday	5:50 PM		Women 3000m	Finals	Start List	Result		Scheduled
Saturday	6:20 PM		Men 3000m	Finals	Start List	Result		Scheduled
Saturday	6:45 PM		Women 4x400m Relay	Finals	Start List	Result		Scheduled
Saturday	7:05 PM		Men 4x400m Relay	Finals	Start List	Result		Scheduled
Day	Start		Saturday Field	Rnd	Start List	Result		Status
Saturday	2:00 PM		Men High Jump	Final	Start List	Result		Scheduled
Saturday	2:00 PM		Women Shot Put	Finals	Start List	Result		Scheduled
Saturday	3:30 PM		Men Pole Vault	Final	Start List	Result		Scheduled
Saturday	4:05 PM		Women Triple Jump	Finals	Start List	Result		Scheduled
Saturday	4:30 PM		Men Triple Jump	Finals	Start List	Result		Scheduled
Saturday	4:45 PM		Men Shot Put	Finals	Start List	Result		Scheduled
Day	Start		Pentathlon	Rnd	Start List	Result		Status
Thursday	11:30 AM		Pentathlon 60m Hurdles	Finals	Start List	Result		Scheduled
Thursday	-		Pentathlon High Jump	Finals	Start List	Result		Scheduled
Thursday	-		Pentathlon Shot Put	Finals	Start List	Result		Scheduled
Thursday	-		Pentathlon Long Jump	Finals	Start List	Result		Scheduled
Thursday	4:45 PM		Pentathlon 800m	Final	Start List	Result		Scheduled
			Pentathlon Standings			Scores 		Scheduled
Day	Start		Heptathlon	Rnd	Start List	Result		Status
Thursday	11:00 AM		Heptathlon 60m	Finals	Start List	Result		Scheduled
Thursday	-		Heptathlon Long Jump	Finals	Start List	Result		Scheduled
Thursday	-		Heptathlon Shot Put	Final	Start List	Result		Scheduled
Thursday	-		Heptathlon High Jump	Finals	Start List	Result		Scheduled
Friday	12:30 PM		Heptathlon 60m Hurdles	Finals	Start List	Result		Scheduled
Friday	-		Heptathlon Pole Vault	Finals	Start List	Result		Scheduled
Friday	6:05 PM		Heptathlon 1000m	Final	Start List	Result		Scheduled
			Heptathlon Standings			Scores 		Scheduled


Multiple events have prelims and finals. Athletes who place in the top 8 of each event score points for their team in the following fashion: 
1st: 10
2nd: 8
3rd: 6
4th: 5
5th: 4
6th: 3
7th: 2
8th: 1

The live result website also contains start lists, which show what athletes from each team are scheduled to race. 

I want to build a scraper that will analyze all of the completed events for total points scored up to that point, as well as the start lists for the races yet to be completed, to calculate a potential number of points a team could still score based on what athletes they have in the remaining events. So a analysis of "Points Possible" for each team would be created. But it also needs to use logic that when scoring for one team, that takes away points from another team, so there could be a lot of different ways to analyze this part of the report. For instance, if a team wins an event with an athlete that automatically removes the opportunity for another team to score that point, so there could be multiple ways to show a "Points possible" chart. How would this best be completed? 

The scraper should be able to click through the website and will need to be able to recognize final results from prelim results, and also understand that the heptathlon and pentathlon are not scored until all the events within it are completed.


As an additional analysis, season rankings for each event could also be compared against the athletes actually scheduled to race in the remaining events, and a projected score based on the rankings could also be calculated. 

The steps would be: 
1) Scrape site for completed results and upcoming events/athletes in those events. It will need to differentiate between prelim start lists and results, and final start lists and results. 
2) Create a "Current team ranking/score"
3) Create a "points possible and projected final team scores"
4) Compare against pre-meet event rankings txt file for athletes rankings who are scheduled to still run and create a "mock score" based on those rankings. 




