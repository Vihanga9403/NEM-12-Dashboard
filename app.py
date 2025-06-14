import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# — Streamlit setup —
st.set_page_config(layout="wide", page_title="🔌 NEM12 Dashboard")
st.title("🔌 NEM12 Energy Dashboard")

# — File uploader —
uploaded_file = st.file_uploader("Upload NEM12 CSV", type="csv")
if not uploaded_file:
    st.info("Please upload a NEM12 CSV file to begin.")
    st.stop()           # <<— this prevents pd.read_csv from ever seeing None

# — 1) Read raw CSV & ensure Record column is integer —
raw = pd.read_csv(uploaded_file, header=None, dtype=str, low_memory=False)
raw.iloc[:, 0] = raw.iloc[:, 0].astype(int)

# — 2) Locate the two Record==200 markers for splitting —
header_idxs = raw.index[raw.iloc[:, 0] == 200].tolist()
if len(header_idxs) < 2:
    st.error("Need at least two `Record==200` headers for consumption and generation blocks.")
    st.stop()
hdr_cons, hdr_gen = header_idxs[0], header_idxs[1]

# — 3) Slice out consumption block: immediately after first 200 until next 200 —
cons_block = raw.iloc[hdr_cons + 1 : hdr_gen].reset_index(drop=True)

# — 4) Slice out generation block: immediately after second 200 until third 200 or next 300 rows —
if len(header_idxs) > 2:
    hdr_next = header_idxs[2]
    gen_block = raw.iloc[hdr_gen + 1 : hdr_next].reset_index(drop=True)
else:
    gen_block = raw.iloc[hdr_gen + 1 : hdr_gen + 1 + 300].reset_index(drop=True)

# — 5) Build half-hour headers & rename columns —
time_headers = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0,30)]
new_cols     = ["Record", "Date"] + time_headers

for df in (cons_block, gen_block):
    extras = df.columns[len(new_cols):]
    df.columns = new_cols + list(extras)
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")

# — 6) Compute daily totals and prepare long-form for charts —
def prepare(df):
    df = df.dropna(subset=["Date"]).copy()
    df[time_headers] = df[time_headers].apply(pd.to_numeric, errors="coerce")
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

# — 7) KPI cards for full consumption/gen blocks —
total_cons = df_cons["Daily_kWh"].sum()
total_gen  = df_gen["Daily_kWh"].sum()
net_total  = total_cons - total_gen

peak_cons = cons_long.groupby("Time")["kWh"].mean().idxmax()
peak_gen  = gen_long.groupby("Time")["kWh"].mean().idxmax()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("⚡ Total Consumption",         f"{total_cons:.0f} kWh")
c2.metric("⚡ Total Generation",          f"{total_gen:.0f} kWh")
c3.metric("🔋 Net (Consumption − Gen)",   f"{net_total:.0f} kWh")
c4.metric("⏱️ Peak Cons Interval",       peak_cons)
c5.metric("⏱️ Peak Gen Interval",        peak_gen)

# — 8) Tabs & charts setup —
tabs = st.tabs([
    "⏱️ TOU", 
    "📈 Daily Total (Cons)", 
    "📈 Daily Total (Gen)", 
    "📊 Seasons (Cons)", 
    "📊 Seasons (Gen)"
])

# Common period definitions
periods     = [
    ("Overnight","00:00","05:00"),
    ("Morning" ,"05:00","08:00"),
    ("Day"     ,"08:00","16:00"),
    ("Evening" ,"16:00","22:00"),
    ("Late"    ,"22:00","24:00"),
]
period_cols = ["#9C27B0","#00BCD4","#FFC107","#F44336","#8BC34A"]

# 8.1) Combined TOU
with tabs[0]:
    st.header("Time-of-Use (Consumption vs Generation)")
    avg_c = cons_long.groupby("Time")["kWh"].mean().reindex(time_headers).reset_index()
    avg_g = gen_long .groupby("Time")["kWh"].mean().reindex(time_headers).reset_index()
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
        mode="lines+markers", line=dict(color="red"), name="Avg Cons"
    ))
    fig.add_trace(go.Scatter(
        x=avg_g["Time"], y=avg_g["kWh"],
        mode="lines+markers", line=dict(color="green"), name="Avg Gen"
    ))
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(tickmode="array", tickvals=time_headers[::4], title="Time of Day"),
        yaxis_title="kWh",
        legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True)

# 8.2) Daily Total (Consumption)
with tabs[1]:
    st.header("Daily Total Energy (Consumption)")
    daily_c = (
        df_cons.groupby("Date", as_index=False)["Daily_kWh"]
               .sum()
               .assign(Date=lambda d: pd.to_datetime(d["Date"]))
    )
    daily_c["Weekday"] = daily_c["Date"].dt.weekday < 5
    daily_c["Color"]   = daily_c["Weekday"].map({True:"#1f77b4", False:"#ff7f0e"})
    fig = go.Figure([go.Bar(
        x=daily_c["Date"], y=daily_c["Daily_kWh"],
        marker_color=daily_c["Color"], name="kWh"
    )])
    fig.update_layout(xaxis_title="Date", yaxis_title="kWh")
    st.plotly_chart(fig, use_container_width=True)

# 8.3) Daily Total (Generation)
with tabs[2]:
    st.header("Daily Total Energy (Generation)")
    daily_g = (
        df_gen.groupby("Date", as_index=False)["Daily_kWh"]
              .sum()
              .assign(Date=lambda d: pd.to_datetime(d["Date"]))
    )
    daily_g["Weekday"] = daily_g["Date"].dt.weekday < 5
    daily_g["Color"]   = daily_g["Weekday"].map({True:"#1f77b4", False:"#ff7f0e"})
    fig = go.Figure([go.Bar(
        x=daily_g["Date"], y=daily_g["Daily_kWh"],
        marker_color=daily_g["Color"], name="kWh"
    )])
    fig.update_layout(xaxis_title="Date", yaxis_title="kWh")
    st.plotly_chart(fig, use_container_width=True)

# 8.4 & 8.5) Seasonal Profiles
season_map = {
    12:"Summer",1:"Summer",2:"Summer",
     3:"Autumn",4:"Autumn",5:"Autumn",
     6:"Winter",7:"Winter",8:"Winter",
     9:"Spring",10:"Spring",11:"Spring"
}
season_cols = {
    "Summer":"#1f77b4","Autumn":"#ff7f0e",
    "Winter":"#d62728","Spring":"#2ca02c"
}

for i, (long_df, label) in enumerate([(cons_long, "Consumption"), (gen_long, "Generation")], start=3):
    with tabs[i]:
        st.header(f"Seasonal & Day-Type ({label})")
        df = long_df.copy()
        df["Season"]  = df["Datetime"].dt.month.map(season_map)
        df["DayType"] = df["Datetime"].dt.weekday.map(lambda d: "Weekday" if d<5 else "Weekend")
        avg_s = df.groupby(["Time","Season"])["kWh"].mean().reset_index()
        avg_d = df.groupby(["Time","DayType"])["kWh"].mean().reset_index()
        fig = go.Figure()
        for season, color in season_cols.items():
            d = avg_s[avg_s["Season"] == season]
            fig.add_trace(go.Scatter(
                x=d["Time"], y=d["kWh"],
                mode="lines", name=f"{season} Avg",
                line=dict(color=color, width=2)
            ))
        for dt, dash in [("Weekday","dash"), ("Weekend","dot")]:
            d = avg_d[avg_d["DayType"] == dt]
            fig.add_trace(go.Scatter(
                x=d["Time"], y=d["kWh"],
                mode="lines", name=f"{dt} Avg",
                line=dict(color="black", dash=dash, width=2)
            ))
        fig.update_layout(
            xaxis=dict(
                title="Time of Day",
                categoryorder="array", categoryarray=time_headers,
                tickmode="array", tickvals=[f"{h:02d}:00" for h in range(0,24,3)]
            ),
            yaxis_title="kWh per 30-min Interval",
            legend=dict(orientation="h", y=1.02, x=1),
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

