import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from statsmodels.tsa.arima.model import ARIMA

# — Streamlit setup —
st.set_page_config(layout="wide", page_title="🔌 NEM12 Dashboard")
st.title("🔌 NEM12 Energy Dashboard")

# — File uploader —
uploaded_file = st.file_uploader("Upload NEM12 CSV", type="csv")
if not uploaded_file:
    st.info("Please upload a NEM12 CSV file to begin.")
    st.stop()

# — 1) Read raw CSV & ensure Record column is integer —
raw = pd.read_csv(uploaded_file, header=None, dtype=str, low_memory=False)
raw.iloc[:, 0] = raw.iloc[:, 0].astype(int)

# — 2) Locate ALL the Record==200 header rows —
header_idxs = raw.index[raw.iloc[:, 0] == 200].tolist()
if len(header_idxs) < 2:
    st.error("Need at least two `Record==200` headers for consumption (E1) and generation (B1).")
    st.stop()

# — 3) Classify each header as E1 or B1 by looking at column D (0-based index 3) —
e1_idx = b1_idx = None
for idx in header_idxs:
    marker = str(raw.iat[idx, 3]).strip().upper()
    if marker == "E1":
        e1_idx = idx
    elif marker == "B1":
        b1_idx = idx
if e1_idx is None or b1_idx is None:
    st.error("Couldn’t find both an E1 and a B1 header in your file.")
    st.stop()

# — 4) Helper to find where a block ends (the next header or EOF) —
all_hdrs = sorted(header_idxs) + [len(raw)]
def next_hdr(after_idx):
    for h in all_hdrs:
        if h > after_idx:
            return h
    return len(raw)

# — 5) Slice out the two blocks properly —
cons_block = raw.iloc[e1_idx + 1 : next_hdr(e1_idx)].reset_index(drop=True)
gen_block  = raw.iloc[b1_idx + 1 : next_hdr(b1_idx)].reset_index(drop=True)

# — 6) Build half-hour headers & rename columns —
time_headers = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0,30)]
new_cols     = ["Record", "Date"] + time_headers
for df in (cons_block, gen_block):
    extras = df.columns[len(new_cols):]
    df.columns = new_cols + list(extras)
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")

# — 7) Compute daily totals and prepare long-form for charts —
def prepare(df):
    df = df.dropna(subset=["Date"]).copy()
    df[time_headers] = df[time_headers].apply(pd.to_numeric, errors="coerce").fillna(0)
    df["Daily_kWh"]     = df[time_headers].sum(axis=1)
    df["Daily_Avg_kWh"] = df[time_headers].mean(axis=1)
    long = (
        df
        .melt(id_vars=["Date"], value_vars=time_headers,
              var_name="Time", value_name="kWh")
        .dropna(subset=["kWh"])
    )
    long["Datetime"] = pd.to_datetime(
        long["Date"].dt.strftime("%Y-%m-%d") + " " + long["Time"],
        errors="coerce"
    )
    return df, long.dropna(subset=["Datetime"])

df_cons, cons_long = prepare(cons_block)
df_gen,  gen_long  = prepare(gen_block)

# — 8) KPI cards —
total_cons = df_cons["Daily_kWh"].sum()
total_gen  = df_gen["Daily_kWh"].sum()
net_total  = total_cons - total_gen
peak_cons  = cons_long.groupby("Time")["kWh"].mean().idxmax()
peak_gen   = gen_long.groupby("Time")["kWh"].mean().idxmax()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("⚡ Total Consumption",       f"{total_cons:.0f} kWh")
c2.metric("⚡ Total Generation",        f"{total_gen:.0f} kWh")
c3.metric("🔋 Net (Consumption − Gen)", f"{net_total:.0f} kWh")
c4.metric("⏱️ Peak Cons Interval",      peak_cons)
c5.metric("⏱️ Peak Gen Interval",       peak_gen)

# — 9) Tabs & charts setup —
tabs = st.tabs([
    "⏱️ TOU",
    "📈 Daily Total (Cons)",
    "📈 Daily Total (Gen)",
    "📊 Seasons (Cons)",
    "📊 Seasons (Gen)",
    "🚩 Outliers",
    "🔮 Forecast"
])

# TOU periods and colors
periods     = [
    ("Overnight","00:00","05:00"),
    ("Morning" ,"05:00","08:00"),
    ("Day"     ,"08:00","16:00"),
    ("Evening" ,"16:00","22:00"),
    ("Late"    ,"22:00","24:00"),
]
period_cols = ["#9C27B0","#00BCD4","#FFC107","#F44336","#8BC34A"]

# 9.1) Time-of-Use
with tabs[0]:
    st.header("Time-of-Use (Consumption vs Generation)")
    avg_c = cons_long.groupby("Time")["kWh"].mean().reindex(time_headers).reset_index()
    avg_g = gen_long.groupby("Time")["kWh"].mean().reindex(time_headers).reset_index()
    fig = go.Figure()
    for (_, start, end), col in zip(periods, period_cols):
        mask = avg_c["Time"].between(start, end, inclusive="left")
        lvl  = avg_c.loc[mask, "kWh"].mean()
        fig.add_trace(go.Bar(
            x=avg_c["Time"],
            y=[lvl if m else None for m in mask],
            marker_color=col, opacity=0.3, showlegend=False
        ))
    fig.add_trace(go.Scatter(
        x=avg_c["Time"], y=avg_c["kWh"],
        mode="lines+markers", line=dict(color="#1f77b4"), name="Avg Cons"
    ))
    fig.add_trace(go.Scatter(
        x=avg_g["Time"], y=avg_g["kWh"],
        mode="lines+markers", line=dict(color="#ff7f0e"), name="Avg Gen"
    ))
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(tickmode="array", tickvals=time_headers[::4], title="Time of Day"),
        yaxis_title="kWh",
        legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True)

# 9.2) Daily Total (Consumption)
with tabs[1]:
    st.header("Daily Total Energy (Consumption)")
    daily_c = df_cons.groupby("Date", as_index=False)["Daily_kWh"].sum()
    daily_c["Weekday"] = daily_c["Date"].dt.weekday < 5
    daily_c["Color"]   = daily_c["Weekday"].map({True:"#1f77b4", False:"#ff7f0e"})
    fig = go.Figure([go.Bar(
        x=daily_c["Date"], y=daily_c["Daily_kWh"],
        marker_color=daily_c["Color"], name="kWh"
    )])
    fig.update_layout(xaxis_title="Date", yaxis_title="kWh")
    st.plotly_chart(fig, use_container_width=True)

# 9.3) Daily Total (Generation)
with tabs[2]:
    st.header("Daily Total Energy (Generation)")
    daily_g = df_gen.groupby("Date", as_index=False)["Daily_kWh"].sum()
    daily_g["Weekday"] = daily_g["Date"].dt.weekday < 5
    daily_g["Color"]   = daily_g["Weekday"].map({True:"#1f77b4", False:"#ff7f0e"})
    fig = go.Figure([go.Bar(
        x=daily_g["Date"], y=daily_g["Daily_kWh"],
        marker_color=daily_g["Color"], name="kWh"
    )])
    fig.update_layout(xaxis_title="Date", yaxis_title="kWh")
    st.plotly_chart(fig, use_container_width=True)

# 9.4 & 9.5) Seasonal Profiles
season_map = {
    **{m:"Summer" for m in (12,1,2)},
    **{m:"Autumn" for m in (3,4,5)},
    **{m:"Winter" for m in (6,7,8)},
    **{m:"Spring" for m in (9,10,11)}
}
season_cols = {"Summer":"#1f77b4","Autumn":"#ff7f0e","Winter":"#d62728","Spring":"#2ca02c"}

for i, (long_df, label) in enumerate([(cons_long,"Consumption"),(gen_long,"Generation")], start=3):
    with tabs[i]:
        st.header(f"Seasonal & Day-Type ({label})")
        tmp = long_df.copy()
        tmp["Season"]  = tmp["Datetime"].dt.month.map(season_map)
        tmp["DayType"] = tmp["Datetime"].dt.weekday.map(lambda d:"Weekday" if d<5 else "Weekend")
        avg_s = tmp.groupby(["Time","Season"])["kWh"].mean().reset_index()
        avg_d = tmp.groupby(["Time","DayType"])["kWh"].mean().reset_index()
        fig = go.Figure()
        for season,color in season_cols.items():
            d = avg_s[avg_s["Season"]==season]
            fig.add_trace(go.Scatter(
                x=d["Time"], y=d["kWh"],
                mode="lines", name=f"{season} Avg",
                line=dict(color=color,width=2)
            ))
        for dt,dash in [("Weekday","dash"),("Weekend","dot")]:
            d = avg_d[avg_d["DayType"]==dt]
            fig.add_trace(go.Scatter(
                x=d["Time"], y=d["kWh"],
                mode="lines", name=f"{dt} Avg",
                line=dict(color="black",dash=dash,width=2)
            ))
        fig.update_layout(
            xaxis=dict(
                title="Time of Day",
                categoryorder="array",categoryarray=time_headers,
                tickmode="array",tickvals=[f"{h:02d}:00" for h in range(0,24,3)]
            ),
            yaxis_title="kWh per 30-min Interval",
            legend=dict(orientation="h",y=1.02,x=1),
            hovermode="x unified"
        )
        st.plotly_chart(fig,use_container_width=True)

# 9.6) Outliers tab (markers only, daily-profile colors)
with tabs[5]:
    st.header("🚩 Outliers (Daily Totals)")
    daily = pd.DataFrame({
        "Consumed": df_cons.groupby("Date")["Daily_kWh"].sum(),
        "Generated": df_gen.groupby("Date")["Daily_kWh"].sum()
    })
    daily["Consumed_z"]  = (daily["Consumed"]  - daily["Consumed"].mean())  / daily["Consumed"].std()
    daily["Generated_z"] = (daily["Generated"] - daily["Generated"].mean()) / daily["Generated"].std()
    out_cons = daily.index[daily["Consumed_z"].abs()  > 3]
    out_gen  = daily.index[daily["Generated_z"].abs() > 3]

    fig = go.Figure()
    # consumption line in daily-profile blue
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["Consumed"],
        mode="lines", line=dict(color="#1f77b4"), name="Consumed"
    ))
    # generation line in daily-profile orange
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["Generated"],
        mode="lines", line=dict(color="#ff7f0e"), name="Generated"
    ))
    # outlier markers matching the same colors
    fig.add_trace(go.Scatter(
        x=out_cons, y=daily.loc[out_cons,"Consumed"],
        mode="markers", marker=dict(color="#1f77b4", size=10), name="Outlier Cons"
    ))
    fig.add_trace(go.Scatter(
        x=out_gen, y=daily.loc[out_gen,"Generated"],
        mode="markers", marker=dict(color="#ff7f0e", size=10), name="Outlier Gen"
    ))
    fig.update_layout(xaxis_title="Date", yaxis_title="Daily kWh")
    st.plotly_chart(fig, use_container_width=True)

# 9.7) Forecast tab
with tabs[6]:
    st.header("🔮 7-Day Forecast of Daily Totals")
    daily_cons = df_cons.groupby("Date")["Daily_kWh"].sum()
    daily_gen  = df_gen.groupby("Date")["Daily_kWh"].sum()

    m1 = ARIMA(daily_cons, order=(1,1,1)).fit()
    fc1 = m1.get_forecast(steps=7).predicted_mean
    m2 = ARIMA(daily_gen, order=(1,1,1)).fit()
    fc2 = m2.get_forecast(steps=7).predicted_mean

    start = daily_cons.index.max() + pd.Timedelta(days=1)
    fc_idx = pd.date_range(start, periods=7, freq="D")
    fc1.index = fc2.index = fc_idx

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_cons.index, y=daily_cons,
        name="Historic Cons"
    ))
    fig.add_trace(go.Scatter(
        x=fc1.index, y=fc1,
        mode="lines+markers", line=dict(dash="dash"),
        name="Forecast Cons"
    ))
    fig.add_trace(go.Scatter(
        x=daily_gen.index, y=daily_gen,
        name="Historic Gen"
    ))
    fig.add_trace(go.Scatter(
        x=fc2.index, y=fc2,
        mode="lines+markers", line=dict(dash="dot"),
        name="Forecast Gen"
    ))
    fig.update_layout(xaxis_title="Date", yaxis_title="Daily kWh")
    st.plotly_chart(fig, use_container_width=True)
