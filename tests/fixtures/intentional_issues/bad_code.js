// JavaScript file with intentional issues
function badFormatting() {
    const x=1
  const y=2
    return x+y
}

function unusedVar() {
    var unused = "this is never used";
    return 42;
}

// eslint-disable-next-line no-unused-vars
function typeCoercion(a, b) {
    return a + b;  // can produce NaN
}
