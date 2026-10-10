const PRODUCTS = [
  { id: 1, name: "Apples", price: 3.5, category: "fruit" },
  { id: 2, name: "Bananas", price: 1.2, category: "fruit" },
  { id: 3, name: "Carrots", price: 2.0, category: "vegetable" },
  { id: 4, name: "Spinach", price: 2.8, category: "vegetable" },
  { id: 5, name: "Sourdough", price: 5.0, category: "bakery" },
  { id: 6, name: "Croissant", price: 2.5, category: "bakery" },
];

function productCard(product) {
  return `
    <article class="product-card">
      <h3>${product.name}</h3>
      <p class="price">$${product.price.toFixed(2)}</p>
    </article>`;
}

function renderProducts(products) {
  document.getElementById("product-grid").innerHTML = products.map(productCard).join("");
}

function setupThemeToggle() {
  const button = document.getElementById("theme-toggle");
  button.addEventListener("click", () => {
    const dark = document.body.classList.toggle("dark");
    button.textContent = dark ? "Light mode" : "Dark mode";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  renderProducts(PRODUCTS);
  setupThemeToggle();
});
