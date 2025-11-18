use std::io::{self, Write};
use std::thread;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🚀 SOCA - Rust Bazel Stub");
    println!("===============================");
    println!("Ova verzija je std-only stub za testiranje Bazel build-a.");

    loop {
        println!("\nOdaberite opciju:");
        println!("1. Pozdravna poruka");
        println!("2. Kratko čekanje (1s)");
        println!("3. Izlaz");
        print!("Vaš izbor: ");
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let choice = input.trim();

        match choice {
            "1" => {
                println!("🦀 Pozdrav iz Rust Bazel aplikacije!");
            }
            "2" => {
                println!("⏳ Čekam 1 sekundu...");
                thread::sleep(Duration::from_secs(1));
                println!("✅ Gotovo.");
            }
            "3" => {
                println!("👋 Doviđenja!");
                break;
            }
            _ => {
                println!("❌ Nevažeći izbor, pokušajte ponovo.");
            }
        }
    }

    Ok(())
}
