import streamlit as st
from pymongo import MongoClient
import pandas as pd
from datetime import datetime
import uuid
import time
import plotly.graph_objects as go

# -----------------------------
# 1. Define User Credentials
# -----------------------------
USER_CREDENTIALS = list(st.secrets["passwords"].keys())

def match_orders(selected_market):
    """Continuously matches buy and sell orders in the selected market."""
    trades_executed = 0  # Counter for executed trades

    while True:
        # Fetch the highest buy order
        highest_buy = orders_col.find_one(
            {"market_id": selected_market, "type": "buy"},
            sort=[("price", -1), ("timestamp", 1)]
        )
        
        # Fetch the lowest sell order
        lowest_sell = orders_col.find_one(
            {"market_id": selected_market, "type": "sell"},
            sort=[("price", 1), ("timestamp", 1)]
        )
        
        # If either buy or sell order doesn't exist, exit the loop
        if not highest_buy or not lowest_sell:
            break
        
        # Check if the highest buy price is >= lowest sell price
        if highest_buy['price'] >= lowest_sell['price']:
            buyer_id = highest_buy['user_id']
            seller_id = lowest_sell['user_id']
            
            # Self-trade prevention (excluding "Charlie")
            if buyer_id == seller_id and buyer_id != "Charlie":
                # Skip this pair and optionally handle it differently
                # For simplicity, we'll remove the buy order to prevent blocking
                orders_col.delete_one({"order_id": highest_buy['order_id']})
                st.warning(f"Self-trade detected and prevented for user: {buyer_id}")
                continue  # Proceed to the next pair
            
            # Determine trade volume and price
            trade_volume = min(highest_buy['volume'], lowest_sell['volume'])
            trade_price = lowest_sell['price']  # You can choose a different pricing strategy
            
            # Create the trade record
            trade = {
                "trade_id": str(uuid.uuid4()),
                "market_id": selected_market,
                "buy_order_id": highest_buy['order_id'],
                "sell_order_id": lowest_sell['order_id'],
                "buy_id": buyer_id,
                "sell_id": seller_id,
                "price": trade_price,
                "volume": trade_volume,
                "timestamp": datetime.utcnow()
            }
            trades_col.insert_one(trade)
            
            # Update the buy order volume
            new_buy_volume = highest_buy['volume'] - trade_volume
            if new_buy_volume > 0:
                orders_col.update_one(
                    {"order_id": highest_buy['order_id']},
                    {"$set": {"volume": new_buy_volume}}
                )
            else:
                orders_col.delete_one({"order_id": highest_buy['order_id']})
            
            # Update the sell order volume
            new_sell_volume = lowest_sell['volume'] - trade_volume
            if new_sell_volume > 0:
                orders_col.update_one(
                    {"order_id": lowest_sell['order_id']},
                    {"$set": {"volume": new_sell_volume}}
                )
            else:
                orders_col.delete_one({"order_id": lowest_sell['order_id']})
            
            trades_executed += 1
            st.success(f"Trade executed: {trade_volume} units at price {trade_price}")
        else:
            # No more matching possible
            break
    
    if trades_executed > 0:
        st.info(f"Total Trades Executed: {trades_executed}")
    else:
        st.info("No matching orders available at the moment.")

# -----------------------------
# 2. Initialize Session State
# -----------------------------
# Initialize session state variables for authentication
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ""

# -----------------------------
# 3. Authentication Functions
# -----------------------------
def login():
    """Display a login form and authenticate the user."""
    with st.form("login_form", clear_on_submit=True):
        st.header("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            if str(username) in USER_CREDENTIALS:
                if (st.secrets.passwords[username]) == password:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.success("Logged in successfully!")
            else:
                st.error("Invalid username or password.")

def logout():
    """Log the user out by clearing session state."""
    if st.button("Logout"):
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""
        st.success("Logged out successfully!")

# -----------------------------
# 4. Display Login Form and Logout Button
# -----------------------------
# Login form at the top
if not st.session_state['logged_in']:
    login()
else:
    # Show logout button and user info
    st.info(f"Logged in!")
    logout()

# -----------------------------
# 5. MongoDB Connection
# -----------------------------
MONGO_CONNECTION_STRING = st.secrets['MONGO_CONNECTION_STRING']

try:
    client = MongoClient(MONGO_CONNECTION_STRING)
    db = client['thesis-betting']
    markets_col = db['markets']
    orders_col = db['orders']
    trades_col = db['trades']
    newsfeed_col = db['newsfeed']  # Added Newsfeed collection
except Exception as e:
    st.error(f"Error connecting to MongoDB: {e}")
    st.stop()

# -----------------------------
# 6. Streamlit Layout with Tabs
# -----------------------------
st.title("Thesis Marks Betting App")

# Create tabs
tab_main, tab_recent_trades, tab_newsfeed = st.tabs(["Market Trading", "Recent Trades", "Newsfeed"])

with tab_main:
    # -----------------------------
    # 7. Refresh Button
    # -----------------------------
    refresh_clicked = st.button("Refresh")
    if refresh_clicked:
        st.write("Data refreshed.")

    # -----------------------------
    # 8. Plotly Chart: EMA and Order Book Highlights
    # -----------------------------
    def plot_ema_and_order_book(selected_market):
        # Fetch Trades for the selected market, sorted by timestamp ascending
        trades = list(trades_col.find({"market_id": selected_market}).sort("timestamp", 1))
        
        if trades:
            trades_df = pd.DataFrame(trades)
            trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
            trades_df.sort_values('timestamp', inplace=True)
            
            # Calculate EMA (e.g., 10-period)
            trades_df['EMA'] = trades_df['price'].ewm(span=10, adjust=False).mean()
            
            # Get highest buy and lowest sell offers
            highest_buy_order = orders_col.find_one({"market_id": selected_market, "type": "buy"}, sort=[("price", -1)])
            lowest_sell_order = orders_col.find_one({"market_id": selected_market, "type": "sell"}, sort=[("price", 1)])
            
            highest_buy = highest_buy_order['price'] if highest_buy_order else None
            lowest_sell = lowest_sell_order['price'] if lowest_sell_order else None

            # Find the most recent trade price
            last_trade_price = trades_df.iloc[-1]['price']

            
            # Create Plotly Figure
            fig = go.Figure()

            # Add trades as black diamonds
            fig.add_trace(
                go.Scatter(
                    x=trades_df['timestamp'],
                    y=trades_df['price'],
                    mode='markers',
                    marker=dict(symbol='diamond', color='black', size=10),
                    name='Trades'
                )
            )

            # Add the most recent trade price as a horizontal dashed black line
            fig.add_trace(
                go.Scatter(
                    x=[trades_df['timestamp'].min(), trades_df['timestamp'].max()],
                    y=[last_trade_price, last_trade_price],
                    mode='lines',
                    name='Last Trade Price',
                    line=dict(color='black', dash='dash')
                )
            )

            
            # Add EMA line
            fig.add_trace(
                go.Scatter(
                    x=trades_df['timestamp'],
                    y=trades_df['EMA'],
                    mode='lines',
                    name='EMA (10)',
                    line=dict(color='blue')
                )
            )
            
            # Add Highest Buy horizontal line
            if highest_buy is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[trades_df['timestamp'].min(), trades_df['timestamp'].max()],
                        y=[highest_buy, highest_buy],
                        mode='lines',
                        name='Highest Buy',
                        line=dict(color='green', dash='dash')
                    )
                )
            
            # Add Lowest Sell horizontal line
            if lowest_sell is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[trades_df['timestamp'].min(), trades_df['timestamp'].max()],
                        y=[lowest_sell, lowest_sell],
                        mode='lines',
                        name='Lowest Sell',
                        line=dict(color='red', dash='dash')
                    )
                )
            
            # Update layout
            fig.update_layout(
                xaxis_title="Time",
                yaxis_title="Price",
                legend=dict(x=0, y=1.2, orientation="h"),
                margin=dict(l=40, r=40, t=40, b=40)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No trades available to display the EMA chart.")

    # -----------------------------
    # 9. Display Markets
    # -----------------------------
    markets = markets_col.find()
    market_list = list(markets)
    
    # Ensure there are markets available
    if not market_list:
        st.error("No markets available. Please contact the administrator.")
        st.stop()
    
    # Create a mapping from display name to market_id
    market_display_names = [m['market_id'].title() for m in market_list]
    market_id_map = {m['market_id'].title(): m['market_id'] for m in market_list}
    
    selected_display_market = st.selectbox("Select a Market", market_display_names)
    selected_market = market_id_map[selected_display_market]
    
    # Plot EMA and Order Book Highlights
    plot_ema_and_order_book(selected_market)
    
    st.header(f"Order Book for {selected_display_market}")
    
    # -----------------------------
    # 10. Fetch and Display Orders
    # -----------------------------
    buy_orders = list(orders_col.find({"market_id": selected_market, "type": "buy"}).sort("price", -1))
    sell_orders = list(orders_col.find({"market_id": selected_market, "type": "sell"}).sort("price", 1))
    
    def create_order_df(orders, order_type):
        if orders:
            df = pd.DataFrame(orders)
            # Ensure all required columns exist
            expected_columns = ['price', 'volume', 'user_id', 'timestamp']
            # Select only existing columns to avoid KeyError
            existing_columns = [col for col in expected_columns if col in df.columns]
            df = df[existing_columns]
            # If some columns are missing, add them with default values
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = None
            # Reorder columns
            df = df[expected_columns]
            # Format timestamp for better readability
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
            # Limit to the first 7 rows
            df = df.head(7)
        else:
            # Create an empty DataFrame with the desired columns
            df = pd.DataFrame(columns=['price', 'volume', 'user_id', 'timestamp'])
        return df
    
    # Display Order Book
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Buy Orders")
        buy_df = create_order_df(buy_orders, "Buy")
        if buy_df.empty:
            st.info("No buy orders available.")
        else:
            st.dataframe(buy_df)
    
    with col2:
        st.subheader("Sell Orders")
        sell_df = create_order_df(sell_orders, "Sell")
        if sell_df.empty:
            st.info("No sell orders available.")
        else:
            st.dataframe(sell_df)
    
    # -----------------------------
    # 11. Order Submission
    # -----------------------------
    st.subheader("Submit an Order")
    order_type = st.selectbox("Order Type", ["buy", "sell"], key="order_type_select")
    #price = st.number_input("Price", min_value=0, step=1, key="price_input")
    price = st.number_input("Price", min_value=0, max_value=100, step=1, key="price_input")
    volume = st.number_input("Volume", min_value=1, max_value=10, step=1, key="volume_input")  # Set max_value=10
    submit_order = st.button("Submit Order")
    
    if submit_order:
        if not st.session_state['logged_in']:
            st.error("Must be logged in to trade.")
        elif price <= 0 or volume <= 0:
            st.error("Price and Volume must be greater than 0.")
        else:
            # Check if volume is <=10 (redundant if st.number_input max=10, but for safety)
            if volume > 10:
                st.error("Maximum volume per trade is 10.")
            else:
                order = {
                    "order_id": str(uuid.uuid4()),
                    "market_id": selected_market,
                    "user_id": st.session_state['username'],  # Use authenticated username
                    "type": order_type,
                    "price": price,
                    "volume": volume,
                    "timestamp": datetime.utcnow()
                }
                try:
                    orders_col.insert_one(order)
                    st.success("Order submitted successfully!")
                    # Automatically attempt to match orders after submission
                    # Delay matching by a few seconds to simulate "a few seconds after submission"
                    time.sleep(1)  # 1-second delay
                    match_orders(selected_market)
                    
                    # Perform matching
                    # Fetch the latest orders again after delay
                    buy_orders = list(orders_col.find({"market_id": selected_market, "type": "buy"}).sort("price", -1))
                    sell_orders = list(orders_col.find({"market_id": selected_market, "type": "sell"}).sort("price", 1))

                    # Perform matching logic with self-trade prevention
                    if buy_orders and sell_orders:
                        highest_buy = buy_orders[0]
                        lowest_sell = sell_orders[0]
                        if highest_buy['price'] >= lowest_sell['price']:
                            # Extract user IDs
                            buyer_id = highest_buy['user_id']
                            seller_id = lowest_sell['user_id']

                            # Check if the buyer and seller are the same user and not "Charlie"
                            if buyer_id == seller_id and buyer_id != "Charlie":
                                st.warning("Cannot trade with yourself.")
                            else:
                                trade_volume = min(highest_buy['volume'], lowest_sell['volume'])
                                trade_price = lowest_sell['price']  # Price agreed is sell price

                                # Create Trade with buy_id and sell_id
                                trade = {
                                    "trade_id": str(uuid.uuid4()),
                                    "market_id": selected_market,
                                    "buy_order_id": highest_buy['order_id'],
                                    "sell_order_id": lowest_sell['order_id'],
                                    "buy_id": buyer_id,
                                    "sell_id": seller_id,
                                    "price": trade_price,
                                    "volume": trade_volume,
                                    "timestamp": datetime.utcnow()
                                }
                                trades_col.insert_one(trade)

                                # Update Orders
                                orders_col.update_one(
                                    {"order_id": highest_buy['order_id']},
                                    {"$inc": {"volume": -trade_volume}}
                                )
                                orders_col.update_one(
                                    {"order_id": lowest_sell['order_id']},
                                    {"$inc": {"volume": -trade_volume}}
                                )

                                # Remove orders if volume is 0
                                if highest_buy['volume'] - trade_volume <= 0:
                                    orders_col.delete_one({"order_id": highest_buy['order_id']})
                                if lowest_sell['volume'] - trade_volume <= 0:
                                    orders_col.delete_one({"order_id": lowest_sell['order_id']})

                                st.success(f"Trade executed: {trade_volume} units at price {trade_price}")
                        else:
                            st.info("No matching orders available at the moment.")
                    else:
                        st.info("Not enough orders to match.")
                except Exception as e:
                    st.error(f"Failed to submit order: {e}")

    # -----------------------------
    # 12. Automatic Matching Mechanism
    # -----------------------------
    # Since we are not using st_autorefresh or st.experimental_rerun, automatic matching on time intervals isn't feasible.
    # Instead, matching occurs after order submission.

# -----------------------------
# 12. Order Matching Function
# -----------------------------

with tab_recent_trades:
    # -----------------------------
    # 13. Display Recent Trades Across All Markets
    # -----------------------------
    st.header("Recent Trades Across All Markets")

    # Fetch the 20 most recent trades across all markets, sorted by timestamp descending
    trades = list(trades_col.find().sort("timestamp", -1).limit(20))
    
    if trades:
        trades_df = pd.DataFrame(trades)
        
        # Check if 'market_id' exists in the trade documents
        if 'market_id' not in trades_df.columns:
            st.error("Trade documents do not contain 'market_id'.")
            st.stop()
        
        # Select relevant columns, including 'market_id' to identify the market
        trades_df = trades_df[[
            'trade_id',
            'market_id',  # Included to identify the market
            'buy_id',
            'sell_id',
            'price',
            'volume',
            'timestamp'
        ]]
        
        # Optional: Map 'market_id' to a more readable market name
        # Assuming 'markets_col' contains 'market_id' and 'market_name' fields
        markets = list(markets_col.find({}, {"market_id": 1, "market_name": 1}))
        market_id_map = {market['market_id']: market.get('market_name', market['market_id']) for market in markets}
        trades_df['market_name'] = trades_df['market_id'].map(market_id_map)
        
        # Reorder columns to place 'market_name' next to 'market_id' or replace 'market_id'
        trades_df = trades_df[[
            'trade_id',
            'market_id',
            'market_name',  # Added for readability
            'buy_id',
            'sell_id',
            'price',
            'volume',
            'timestamp'
        ]]
        
        # Format timestamp for better readability
        trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Display the DataFrame in the app
        st.dataframe(trades_df)
    else:
        st.info("No trades have been executed yet.")

with tab_newsfeed:
    # -----------------------------
    # 14. Newsfeed Section
    # -----------------------------
    st.header("Newsfeed")

    # -----------------------------
    # 14.1 Submit a Comment
    # -----------------------------
    def submit_comment():
        """Handles the submission of a new comment to the newsfeed."""
        with st.form("newsfeed_form", clear_on_submit=True):
            comment = st.text_area("Enter your comment (max 100 characters):", height=100)
            submit = st.form_submit_button("Post Comment")
            if submit:
                if not st.session_state['logged_in']:
                    st.error("Must be logged in to post a comment.")
                elif not comment.strip():
                    st.error("Comment cannot be empty.")
                elif len(comment) > 100:
                    st.error("Comment exceeds 100 characters.")
                else:
                    newsfeed_entry = {
                        "comment_id": str(uuid.uuid4()),
                        "comment": comment.strip(),
                        "timestamp": datetime.utcnow()
                        # Note: Not storing user_id to maintain anonymity
                    }
                    try:
                        newsfeed_col.insert_one(newsfeed_entry)
                        st.success("Comment posted successfully!")
                    except Exception as e:
                        st.error(f"Failed to post comment: {e}")

    submit_comment()

    # -----------------------------
    # 14.2 Display Recent Comments
    # -----------------------------
    st.subheader("Most Recent Comments")
    recent_comments = list(newsfeed_col.find().sort("timestamp", -1).limit(25))
    
    if recent_comments:
        comments_df = pd.DataFrame(recent_comments)
        # Select relevant columns and exclude any user identifiers
        comments_df = comments_df[[
            'comment',
            'timestamp'
        ]]
        # Format timestamp for better readability
        comments_df['timestamp'] = pd.to_datetime(comments_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        # Rename columns for clarity
        comments_df.rename(columns={'comment': 'Comment', 'timestamp': 'Posted At'}, inplace=True)
        st.table(comments_df)
    else:
        st.info("No comments have been posted yet.")