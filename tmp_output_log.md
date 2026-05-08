python test_sse_stream.py --company "Unilever" --metrics "Revenue, EBITDA"
Connecting to: http://localhost:8000/api/spread
Company: Unilever
Years: ['2021', '2022', '2023', '2024', '2025']
Metrics (2): ['Revenue', 'EBITDA']
------------------------------------------------------------
[VERIFY] 2021: ok  nodes=83  leaves_with_text=75
[VERIFY] 2022: ok  nodes=170  leaves_with_text=150
[VERIFY] 2023: ok  nodes=257  leaves_with_text=225
[VERIFY] 2024: ok  nodes=357  leaves_with_text=279
[VERIFY] 2025: ok  nodes=271  leaves_with_text=225
[RESOLVED] row=0  Revenue  year=2021  value=52444.0
           source_location=Unilever 2021, pp. 117-120
           component: Revenue = 52444.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Operating cashflow  year=2021  value=7972.0
           source_location=Unilever 2021, pp. 117-120
           component: Operating cashflow = 7972.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Investing cashflow  year=2021  value=-3246.0
           source_location=Unilever 2021, pp. 117-120
           component: Investing cashflow = -3246.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Financing cashflow  year=2021  value=-7099.0
           source_location=Unilever 2021, pp. 117-120
           component: Financing cashflow = -7099.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  w/w Dividends  year=2021  value=-4483.0
           source_location=Unilever 2021, pp. 117-120
           component: w/w Dividends = -4483.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Capital Expenditure  year=2021  value=-1108.0
           source_location=Unilever 2021, pp. 117-120
           component: Capital Expenditure = -1108.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Net Worth  year=2021  value=69179.0
           source_location=Unilever 2021, pp. 170-178
           component: Net Worth = 69179.0  (Unilever 2021, pp. 170-178)
[RESOLVED] row=None  Gross Profit  year=2021  value=22185.0
           source_location=Unilever 2021, pp. 126-127
           component: Gross Profit = 22185.0  (Unilever 2021, pp. 126-127)
[RESOLVED] row=None  Interest Expense (Net)  year=2021  value=-354.0
           source_location=Unilever 2021, pp. 117-120
           component: Interest Expense (Net) = -354.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Cash + Mkt Securities  year=2021  value=4571.0
           source_location=Unilever 2021, pp. 117-120
           component: Cash + Mkt Securities = 4571.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Change in Working Capital  year=2021  value=-47.0
           source_location=Unilever 2021, pp. 117-120
           component: Change in Working Capital = -47.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  Gross Profit Margin %  year=2021  value=18.4
           source_location=Unilever 2021, pp. 39-47
           component: Gross Profit Margin % = 18.4  (Unilever 2021, pp. 39-47)
[RESOLVED] row=None  Operating Profit  year=2021  value=8702.0
           source_location=Unilever 2021, pp. 117-120
           component: Operating Profit = 8702.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=1  EBITDA  year=2021  value=11382.0
           source_location=Unilever 2021, pp. 39-47
           component: EBITDA = 11382.0  (Unilever 2021, pp. 39-47)
[RESOLVED] row=None  Operating Profit Margin %  year=2021  value=16.6
           source_location=Unilever 2021, pp. 35-39
           component: Operating Profit Margin % = 16.6  (Unilever 2021, pp. 35-39)
[RESOLVED] row=None  Net Profit  year=2021  value=6621.0
           source_location=Unilever 2021, pp. 117-120
           component: Net Profit = 6621.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  EBITDA Margin %  year=2021  value=18.4
           source_location=Unilever 2021, pp. 123-125
           component: EBITDA Margin % = 18.4  (Unilever 2021, pp. 123-125)
[PARTIAL] row=None  Total Ext. Funded Debt  year=2021  value=None
           formula=Short Term Debt + Long Term Debt
           component: Short Term Debt = None  ()
           component: Long Term Debt = None  ()
[RESOLVED] row=None  Tangible Net Worth  year=2021  value=50918.0
           formula=Net Worth - Net Intangible Assets
           source_location=Unilever 2021, pp. 170-178
           component: Net Worth = 69179.0  (Unilever 2021, pp. 170-178)
           component: Net Intangible Assets = 18261.0  (Unilever 2021, pp. 139-141)
[RESOLVED] row=None  Working Capital Days  year=2021  value=75.74945
           formula=(Receivables / Revenue * 365) + (Inventory / Cost of Sales * 365) - (Payables / Cost of Sales * 365)
           source_location=Unilever 2021, pp. 145-145
           component: Receivables = 3582.0  (Unilever 2021, pp. 145-145)
           component: Revenue = 52444.0  (Unilever 2021, pp. 117-120)
           component: Inventory = 4683.0  (Unilever 2021, pp. 144-144)
           component: Cost of Sales = -30259.0  (Unilever 2021, pp. 126-127)
           component: Payables = 8896.0  (Unilever 2021, pp. 146-146)
[RESOLVED] row=None  Free cashflow  year=2021  value=2381.0
           formula=Operating cashflow + Capital Expenditure + w/w Dividends
           source_location=Unilever 2021, pp. 117-120
           component: Operating cashflow = 7972.0  (Unilever 2021, pp. 117-120)
           component: Capital Expenditure = -1108.0  (Unilever 2021, pp. 117-120)
           component: w/w Dividends = -4483.0  (Unilever 2021, pp. 117-120)
[RESOLVED] row=None  NOCF / Interest  year=2021  value=-22.51977
           formula=Operating cashflow / Interest Expense (Net)
           source_location=Unilever 2021, pp. 117-120
           component: Operating cashflow = 7972.0  (Unilever 2021, pp. 117-120)
           component: Interest Expense (Net) = -354.0  (Unilever 2021, pp. 117-120)
[PARTIAL] row=None  Ext. Gearing (TFD/TNW)  year=2021  value=None
           formula=Total Ext. Funded Debt / Tangible Net Worth
           component: Total Ext. Funded Debt = None  ()
           component: Tangible Net Worth = 50918.0  (Unilever 2021, pp. 170-178)
[PARTIAL] row=None  Net Funded Debt  year=2021  value=None
           formula=Total Ext. Funded Debt - Cash + Mkt Securities
           component: Total Ext. Funded Debt = None  ()
           component: Cash + Mkt Securities = 4571.0  (Unilever 2021, pp. 117-120)
[PARTIAL] row=None  TFD / EBITDA  year=2021  value=None
           formula=Total Ext. Funded Debt / EBITDA
           component: Total Ext. Funded Debt = None  ()
           component: EBITDA = 11382.0  (Unilever 2021, pp. 39-47)
[PARTIAL] row=None  NFD / EBITDA  year=2021  value=None
           formula=Net Funded Debt / EBITDA
           component: Net Funded Debt = None  ()
           component: EBITDA = 11382.0  (Unilever 2021, pp. 39-47)
[RESOLVED] row=0  Revenue  year=2022  value=60073.0
           source_location=Unilever 2022, pp. 13-15
           component: Revenue = 60073.0  (Unilever 2022, pp. 13-15)
[RESOLVED] row=None  Operating cashflow  year=2022  value=7282.0
           source_location=Unilever 2022, pp. 57-63
           component: Operating cashflow = 7282.0  (Unilever 2022, pp. 57-63)
[RESOLVED] row=None  Investing cashflow  year=2022  value=2453.0
           source_location=Unilever 2022, pp. 153-157
           component: Investing cashflow = 2453.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=None  Financing cashflow  year=2022  value=-8890.0
           source_location=Unilever 2022, pp. 187-188
           component: Financing cashflow = -8890.0  (Unilever 2022, pp. 187-188)
[RESOLVED] row=None  w/w Dividends  year=2022  value=-4329.0
           source_location=Unilever 2022, pp. 175-175
           component: w/w Dividends = -4329.0  (Unilever 2022, pp. 175-175)
[RESOLVED] row=None  Capital Expenditure  year=2022  value=-1456.0
           source_location=Unilever 2022, pp. 178-178
           component: Capital Expenditure = -1456.0  (Unilever 2022, pp. 178-178)
[RESOLVED] row=None  Net Worth  year=2022  value=67226.0
           source_location=Unilever 2022, pp. 212-217
           component: Net Worth = 67226.0  (Unilever 2022, pp. 212-217)
[RESOLVED] row=None  Gross Profit  year=2022  value=24167.0
           source_location=Unilever 2022, pp. 159-162
           component: Gross Profit = 24167.0  (Unilever 2022, pp. 159-162)
[RESOLVED] row=None  Interest Expense (Net)  year=2022  value=-493.0
           source_location=Unilever 2022, pp. 153-157
           component: Interest Expense (Net) = -493.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=None  Cash + Mkt Securities  year=2022  value=4326.0
           source_location=Unilever 2022, pp. 197-198
           component: Cash + Mkt Securities = 4326.0  (Unilever 2022, pp. 197-198)
[RESOLVED] row=None  Change in Working Capital  year=2022  value=-422.0
           source_location=Unilever 2022, pp. 153-157
           component: Change in Working Capital = -422.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=None  Gross Profit Margin %  year=2022  value=40.22939
           formula=(Gross Profit / Revenue) * 100
           source_location=Unilever 2022, pp. 159-162
           component: Gross Profit = 24167.0  (Unilever 2022, pp. 159-162)
           component: Revenue = 60073.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=None  Operating Profit  year=2022  value=10755.0
           source_location=Unilever 2022, pp. 153-157
           component: Operating Profit = 10755.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=1  EBITDA  year=2022  value=8379.0
           formula=Profit before Taxes + Interest Expense (Net) + Depreciation + Amortization
           source_location=Unilever 2022, pp. 153-157
           component: Profit before Taxes = 10337.0  (Unilever 2022, pp. 153-157)
           component: Interest Expense (Net) = -486.0  (Unilever 2022, pp. 171-172)
           component: Depreciation = -1017.0  (Unilever 2022, pp. 178-178)
           component: Amortization = -455.0  (Unilever 2022, pp. 175-178)
[RESOLVED] row=None  Operating Profit Margin %  year=2022  value=17.9
           source_location=Unilever 2022, pp. 55-56
           component: Operating Profit Margin % = 17.9  (Unilever 2022, pp. 55-56)
[RESOLVED] row=None  Net Profit  year=2022  value=8269.0
           source_location=Unilever 2022, pp. 153-157
           component: Net Profit = 8269.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=None  EBITDA Margin %  year=2022  value=18.99023
           formula=(EBITDA / Revenue) * 100
           source_location=Unilever 2022, pp. 159-162
           component: EBITDA = 11408.0  (Unilever 2022, pp. 159-162)
           component: Revenue = 60073.0  (Unilever 2022, pp. 153-157)
[PARTIAL] row=None  Total Ext. Funded Debt  year=2022  value=None
           formula=Short Term Debt + Long Term Debt
           component: Short Term Debt = None  ()
           component: Long Term Debt = None  ()
[RESOLVED] row=None  Tangible Net Worth  year=2022  value=48346.0
           formula=Net Worth - Net Intangible Assets
           source_location=Unilever 2022, pp. 212-217
           component: Net Worth = 67226.0  (Unilever 2022, pp. 212-217)
           component: Net Intangible Assets = 18880.0  (Unilever 2022, pp. 175-178)
[RESOLVED] row=None  Working Capital Days  year=2022  value=80.15419
           formula=(Receivables / Revenue * 365) + (Inventory / Cost of Sales * 365) - (Payables / Cost of Sales * 365)
           source_location=Unilever 2022, pp. 182-182
           component: Receivables = 4544.0  (Unilever 2022, pp. 182-182)
           component: Revenue = 60073.0  (Unilever 2022, pp. 13-15)
           component: Inventory = 5931.0  (Unilever 2022, pp. 181-182)
           component: Cost of Sales = -35906.0  (Unilever 2022, pp. 162-164)
           component: Payables = 11100.0  (Unilever 2022, pp. 183-184)
[RESOLVED] row=None  Free cashflow  year=2022  value=1497.0
           formula=Operating cashflow + Capital Expenditure + w/w Dividends
           source_location=Unilever 2022, pp. 57-63
           component: Operating cashflow = 7282.0  (Unilever 2022, pp. 57-63)
           component: Capital Expenditure = -1456.0  (Unilever 2022, pp. 178-178)
           component: w/w Dividends = -4329.0  (Unilever 2022, pp. 175-175)
[RESOLVED] row=None  NOCF / Interest  year=2022  value=-14.77079
           formula=Operating cashflow / Interest Expense (Net)
           source_location=Unilever 2022, pp. 57-63
           component: Operating cashflow = 7282.0  (Unilever 2022, pp. 57-63)
           component: Interest Expense (Net) = -493.0  (Unilever 2022, pp. 153-157)
[PARTIAL] row=None  Ext. Gearing (TFD/TNW)  year=2022  value=None
           formula=Total Ext. Funded Debt / Tangible Net Worth
           component: Total Ext. Funded Debt = None  ()
           component: Tangible Net Worth = 48346.0  (Unilever 2022, pp. 212-217)
[PARTIAL] row=None  Net Funded Debt  year=2022  value=None
           formula=Total Ext. Funded Debt - Cash + Mkt Securities
           component: Total Ext. Funded Debt = None  ()
           component: Cash + Mkt Securities = 4326.0  (Unilever 2022, pp. 197-198)
[PARTIAL] row=None  TFD / EBITDA  year=2022  value=None
           formula=Total Ext. Funded Debt / EBITDA
           component: Total Ext. Funded Debt = None  ()
           component: EBITDA = 8379.0  (Unilever 2022, pp. 153-157)
[PARTIAL] row=None  NFD / EBITDA  year=2022  value=None
           formula=Net Funded Debt / EBITDA
           component: Net Funded Debt = None  ()
           component: EBITDA = 8379.0  (Unilever 2022, pp. 153-157)
[RESOLVED] row=0  Revenue  year=2023  value=59604.0
           source_location=Unilever 2023, pp. 176-180
           component: Revenue = 59604.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  Operating cashflow  year=2023  value=11561.0
           source_location=Unilever 2023, pp. 59-68
           component: Operating cashflow = 11561.0  (Unilever 2023, pp. 59-68)
[RESOLVED] row=None  Investing cashflow  year=2023  value=-2294.0
           source_location=Unilever 2023, pp. 176-180
           component: Investing cashflow = -2294.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  Financing cashflow  year=2023  value=-7193.0
           source_location=Unilever 2023, pp. 176-180
           component: Financing cashflow = -7193.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  w/w Dividends  year=2023  value=-4327.0
           source_location=Unilever 2023, pp. 197-197
           component: w/w Dividends = -4327.0  (Unilever 2023, pp. 197-197)
[RESOLVED] row=None  Capital Expenditure  year=2023  value=-1502.0
           source_location=Unilever 2023, pp. 201-201
           component: Capital Expenditure = -1502.0  (Unilever 2023, pp. 201-201)
[RESOLVED] row=None  Net Worth  year=2023  value=66755.0
           source_location=Unilever 2023, pp. 230-233
           component: Net Worth = 66755.0  (Unilever 2023, pp. 230-233)
[RESOLVED] row=None  Gross Profit  year=2023  value=94033.0
           formula=Revenue - Cost of Sales
           source_location=Unilever 2023, pp. 230-230
           component: Revenue = 59604.0  (Unilever 2023, pp. 230-230)
           component: Cost of Sales = -34429.0  (Unilever 2023, pp. 186-186)
[RESOLVED] row=None  Interest Expense (Net)  year=2023  value=-486.0
           source_location=Unilever 2023, pp. 176-180
           component: Interest Expense (Net) = -486.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  Cash + Mkt Securities  year=2023  value=5890.0
           source_location=Unilever 2023, pp. 176-180
           component: Cash + Mkt Securities = 5890.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  Change in Working Capital  year=2023  value=814.0
           source_location=Unilever 2023, pp. 230-230
           component: Change in Working Capital = 814.0  (Unilever 2023, pp. 230-230)
[RESOLVED] row=None  Gross Profit Margin %  year=2023  value=42.2
           source_location=Unilever 2023, pp. 13-17
           component: Gross Profit Margin % = 42.2  (Unilever 2023, pp. 13-17)
[RESOLVED] row=None  Operating Profit  year=2023  value=9758.0
           source_location=Unilever 2023, pp. 176-180
           component: Operating Profit = 9758.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=1  EBITDA  year=2023  value=11510.0
           source_location=Unilever 2023, pp. 183-183
           component: EBITDA = 11510.0  (Unilever 2023, pp. 183-183)
[RESOLVED] row=None  Operating Profit Margin %  year=2023  value=16.4
           source_location=Unilever 2023, pp. 59-68
           component: Operating Profit Margin % = 16.4  (Unilever 2023, pp. 59-68)
[RESOLVED] row=None  Net Profit  year=2023  value=7140.0
           source_location=Unilever 2023, pp. 176-180
           component: Net Profit = 7140.0  (Unilever 2023, pp. 176-180)
[RESOLVED] row=None  EBITDA Margin %  year=2023  value=16.7
           source_location=Unilever 2023, pp. 59-68
           component: EBITDA Margin % = 16.7  (Unilever 2023, pp. 59-68)
[PARTIAL] row=None  Total Ext. Funded Debt  year=2023  value=None
           formula=Short Term Debt + Long Term Debt
           component: Short Term Debt = None  ()
           component: Long Term Debt = None  ()
[RESOLVED] row=None  Tangible Net Worth  year=2023  value=48398.0
           formula=Net Worth - Net Intangible Assets
           source_location=Unilever 2023, pp. 230-233
           component: Net Worth = 66755.0  (Unilever 2023, pp. 230-233)
           component: Net Intangible Assets = 18357.0  (Unilever 2023, pp. 198-198)
[RESOLVED] row=None  Working Capital Days  year=2023  value=76.3501
           formula=(Receivables / Revenue * 365) + (Inventory / Cost of Sales * 365) - (Payables / Cost of Sales * 365)
           source_location=Unilever 2023, pp. 204-204
           component: Receivables = 4023.0  (Unilever 2023, pp. 204-204)
           component: Revenue = 59604.0  (Unilever 2023, pp. 176-180)
           component: Inventory = 5477.0  (Unilever 2023, pp. 203-204)
           component: Cost of Sales = -34429.0  (Unilever 2023, pp. 186-186)
           component: Payables = 10355.0  (Unilever 2023, pp. 205-205)
[RESOLVED] row=None  Free cashflow  year=2023  value=5732.0
           formula=Operating cashflow + Capital Expenditure + w/w Dividends
           source_location=Unilever 2023, pp. 59-68
           component: Operating cashflow = 11561.0  (Unilever 2023, pp. 59-68)
           component: Capital Expenditure = -1502.0  (Unilever 2023, pp. 201-201)
           component: w/w Dividends = -4327.0  (Unilever 2023, pp. 197-197)
[RESOLVED] row=None  NOCF / Interest  year=2023  value=-23.78807
           formula=Operating cashflow / Interest Expense (Net)
           source_location=Unilever 2023, pp. 59-68
           component: Operating cashflow = 11561.0  (Unilever 2023, pp. 59-68)
           component: Interest Expense (Net) = -486.0  (Unilever 2023, pp. 176-180)
[PARTIAL] row=None  Ext. Gearing (TFD/TNW)  year=2023  value=None
           formula=Total Ext. Funded Debt / Tangible Net Worth
           component: Total Ext. Funded Debt = None  ()
           component: Tangible Net Worth = 48398.0  (Unilever 2023, pp. 230-233)
[PARTIAL] row=None  Net Funded Debt  year=2023  value=None
           formula=Total Ext. Funded Debt - Cash + Mkt Securities
           component: Total Ext. Funded Debt = None  ()
           component: Cash + Mkt Securities = 5890.0  (Unilever 2023, pp. 176-180)
[PARTIAL] row=None  TFD / EBITDA  year=2023  value=None
           formula=Total Ext. Funded Debt / EBITDA
           component: Total Ext. Funded Debt = None  ()
           component: EBITDA = 11510.0  (Unilever 2023, pp. 183-183)
[PARTIAL] row=None  NFD / EBITDA  year=2023  value=None
           formula=Net Funded Debt / EBITDA
           component: Net Funded Debt = None  ()
           component: EBITDA = 11510.0  (Unilever 2023, pp. 183-183)
[RESOLVED] row=0  Revenue  year=2024  value=60761.0
           source_location=Unilever 2024, pp. 141-145
           component: Revenue = 60761.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=None  Operating cashflow  year=2024  value=12144.0
           source_location=Unilever 2024, pp. 41-51
           component: Operating cashflow = 12144.0  (Unilever 2024, pp. 41-51)
[RESOLVED] row=None  Investing cashflow  year=2024  value=-625.0
           source_location=Unilever 2024, pp. 141-145
           component: Investing cashflow = -625.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=None  Financing cashflow  year=2024  value=-6941.0
           source_location=Unilever 2024, pp. 141-145
           component: Financing cashflow = -6941.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=None  w/w Dividends  year=2024  value=-4320.0
           source_location=Unilever 2024, pp. 162-162
           component: w/w Dividends = -4320.0  (Unilever 2024, pp. 162-162)
[RESOLVED] row=None  Capital Expenditure  year=2024  value=-1738.0
           source_location=Unilever 2024, pp. 166-166
           component: Capital Expenditure = -1738.0  (Unilever 2024, pp. 166-166)
[RESOLVED] row=None  Net Worth  year=2024  value=84318.0
           source_location=Unilever 2024, pp. 195-198
           component: Net Worth = 84318.0  (Unilever 2024, pp. 195-198)
[RESOLVED] row=None  Gross Profit  year=2024  value=27370.0
           source_location=Unilever 2024, pp. 151-151
           component: Gross Profit = 27370.0  (Unilever 2024, pp. 151-151)
[RESOLVED] row=None  Interest Expense (Net)  year=2024  value=-604.0
           source_location=Unilever 2024, pp. 141-145
           component: Interest Expense (Net) = -604.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=None  Cash + Mkt Securities  year=2024  value=6136.0
           source_location=Unilever 2024, pp. 185-185
           component: Cash + Mkt Securities = 6136.0  (Unilever 2024, pp. 185-185)
[RESOLVED] row=None  Change in Working Capital  year=2024  value=-160.0
           source_location=Unilever 2024, pp. 41-51
           component: Change in Working Capital = -160.0  (Unilever 2024, pp. 41-51)
[RESOLVED] row=None  Gross Profit Margin %  year=2024  value=45.0
           source_location=Unilever 2024, pp. 13-17
           component: Gross Profit Margin % = 45.0  (Unilever 2024, pp. 13-17)
[RESOLVED] row=None  Operating Profit  year=2024  value=9400.0
           source_location=Unilever 2024, pp. 141-145
           component: Operating Profit = 9400.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=1  EBITDA  year=2024  value=11024.0
           source_location=Unilever 2024, pp. 13-17
           component: EBITDA = 11024.0  (Unilever 2024, pp. 13-17)
[RESOLVED] row=None  Operating Profit Margin %  year=2024  value=15.5
           source_location=Unilever 2024, pp. 41-51
           component: Operating Profit Margin % = 15.5  (Unilever 2024, pp. 41-51)
[RESOLVED] row=None  Net Profit  year=2024  value=6369.0
           source_location=Unilever 2024, pp. 141-145
           component: Net Profit = 6369.0  (Unilever 2024, pp. 141-145)
[RESOLVED] row=None  EBITDA Margin %  year=2024  value=18.4
           source_location=Unilever 2024, pp. 41-51
           component: EBITDA Margin % = 18.4  (Unilever 2024, pp. 41-51)
[PARTIAL] row=None  Total Ext. Funded Debt  year=2024  value=None
           formula=Short Term Debt + Long Term Debt
           component: Short Term Debt = None  ()
           component: Long Term Debt = None  ()
[RESOLVED] row=None  Tangible Net Worth  year=2024  value=65728.0
           formula=Net Worth - Net Intangible Assets
           source_location=Unilever 2024, pp. 195-198
           component: Net Worth = 84318.0  (Unilever 2024, pp. 195-198)
           component: Net Intangible Assets = 18590.0  (Unilever 2024, pp. 163-165)
[RESOLVED] row=None  Working Capital Days  year=2024  value=80.93306
           formula=(Receivables / Revenue * 365) + (Inventory / Cost of Sales * 365) - (Payables / Cost of Sales * 365)
           source_location=Unilever 2024, pp. 170-170
           component: Receivables = 4227.0  (Unilever 2024, pp. 170-170)
           component: Revenue = 60761.0  (Unilever 2024, pp. 141-145)
           component: Inventory = 5177.0  (Unilever 2024, pp. 169-170)
           component: Cost of Sales = -33391.0  (Unilever 2024, pp. 151-151)
           component: Payables = 10258.0  (Unilever 2024, pp. 171-171)
[RESOLVED] row=None  Free cashflow  year=2024  value=6086.0
           formula=Operating cashflow + Capital Expenditure + w/w Dividends
           source_location=Unilever 2024, pp. 41-51
           component: Operating cashflow = 12144.0  (Unilever 2024, pp. 41-51)
           component: Capital Expenditure = -1738.0  (Unilever 2024, pp. 166-166)
           component: w/w Dividends = -4320.0  (Unilever 2024, pp. 162-162)
[RESOLVED] row=None  NOCF / Interest  year=2024  value=-20.10596
           formula=Operating cashflow / Interest Expense (Net)
           source_location=Unilever 2024, pp. 41-51
           component: Operating cashflow = 12144.0  (Unilever 2024, pp. 41-51)
           component: Interest Expense (Net) = -604.0  (Unilever 2024, pp. 141-145)
[PARTIAL] row=None  Ext. Gearing (TFD/TNW)  year=2024  value=None
           formula=Total Ext. Funded Debt / Tangible Net Worth
           component: Total Ext. Funded Debt = None  ()
           component: Tangible Net Worth = 65728.0  (Unilever 2024, pp. 195-198)
[PARTIAL] row=None  Net Funded Debt  year=2024  value=None
           formula=Total Ext. Funded Debt - Cash + Mkt Securities