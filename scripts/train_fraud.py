from app.fraud import train_and_save

if __name__ == "__main__":
    path = train_and_save()
    print(f"Saved fraud model to {path}")
