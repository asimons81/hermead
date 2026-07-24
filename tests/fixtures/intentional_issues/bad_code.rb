# frozen_string_literal: true

# Ruby file with intentional issues for testing
# Has: unused variable, missing frozen_string_literal in second class,
#       SQL injection pattern, style violations

class Greeter
  def initialize(name)
    @name = name
  end

  def greet
    unused = "this is never used"
    return "Hello, #{@name}"
  end
end

class UserSearch
  def find_user(name)
    # SQL injection vulnerability
    query = "SELECT * FROM users WHERE name = '#{name}'"
    execute(query)
  end

  def execute(sql)
    puts "Executing: #{sql}"
  end
end

# Unused variable at module level
x = 42
